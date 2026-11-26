"""Run command for the Agent Actions CLI."""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import click

from agent_actions.cli.args import DEFAULT_POLL_SECONDS, RunCommandArgs
from agent_actions.cli.cli_decorators import (
    handles_user_errors,
    requires_project,
    sandbox_option,
    scenario_option,
    workflow_option,
)
from agent_actions.cli.exit_codes import (
    EXIT_CODES,
    EXIT_SUCCESS,
    TRACKER_STATUSES,
    RunOutcome,
    actions_with_record_failures,
    classify_outcome,
    report_quota_stop,
)
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config import sandbox
from agent_actions.config.project_paths import ProjectPaths, ProjectPathsFactory
from agent_actions.errors import AgentActionsError, ProviderQuotaStop
from agent_actions.logging.factory import LoggerFactory
from agent_actions.prompt.handler import PromptLoader
from agent_actions.storage.run_lock import hold_run_lock
from agent_actions.tooling.docs.run_tracker import RunTracker
from agent_actions.validation.prompt_validator import PromptValidator

if TYPE_CHECKING:
    from agent_actions.workflow.coordinator import AgentWorkflow

logger = logging.getLogger(__name__)


def batches_still_open(io_dir: Path, workflow_name: str) -> list[str]:
    """The actions with a batch not yet collected, read from the store before any load."""
    import json

    status_file = sandbox.status_file(io_dir)
    try:
        statuses = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Gone or cut short: the batch registry in the store still says what is open.
        statuses = {}
    if not isinstance(statuses, dict):
        statuses = {}
    waiting = {"batch_submitted", "checking_batch"}
    open_actions = {
        action
        for action, details in statuses.items()
        if isinstance(details, dict) and details.get("status") in waiting
    }
    store = sandbox.store_file(io_dir, workflow_name)
    if store.exists():
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
        from agent_actions.storage import get_storage_backend

        backend = get_storage_backend(
            workflow_path=str(io_dir.parent), workflow_name=workflow_name
        )
        backend.initialize()
        try:
            registered = BatchRegistryManager.list_action_names(backend)
            for action in dict.fromkeys([*statuses, *registered]):
                jobs = BatchRegistryManager(backend, action).get_all_jobs().values()
                if any(job.is_in_flight or job.awaits_collection for job in jobs):
                    open_actions.add(action)
        finally:
            backend.close()
    return sorted(open_actions)


def report_scenario(*, only_after_calls: bool = False) -> None:
    """The one line that counts what the sandbox scenario did over the whole command.

    With *only_after_calls*, for a command that an error stopped: no line when the mock
    answered no call.
    """
    line = sandbox.scenario_summary(only_after_calls)
    if line is not None:
        click.echo(line)


def check_declared_outputs(workflow: AgentWorkflow, project_root: Path | None) -> None:
    """Refuse the workflow's declared outputs before any action runs, if they cannot be written."""
    declared = (workflow.config.manager.user_config or {}).get("outputs")
    if not declared or sandbox.is_active():
        return
    from agent_actions.connections.export import check_outputs
    from agent_actions.utils.project_root import find_project_root

    root = project_root or find_project_root(str(Path.cwd())) or Path.cwd()
    check_outputs(declared, root, actions=list(workflow.execution_order))


def write_declared_outputs(workflow: AgentWorkflow, project_root: Path | None, agent: str) -> None:
    """Write the workflow's declared outputs once every action has finished."""
    declared = (workflow.config.manager.user_config or {}).get("outputs")
    if not declared:
        return
    if sandbox.is_active():
        click.echo("SANDBOX: the outputs the workflow declares are not written.")
        return
    from agent_actions.connections.export import write_outputs
    from agent_actions.utils.project_root import find_project_root

    root = project_root or find_project_root(str(Path.cwd())) or Path.cwd()
    try:
        written = write_outputs(
            workflow.storage_backend, declared, root, actions=list(workflow.execution_order)
        )
    except AgentActionsError:
        click.echo(
            "Every action finished, but writing the outputs failed. The results are "
            f"stored: write them again with agac export -w {agent}",
            err=True,
        )
        raise
    for table, count in written.items():
        click.echo(f"Wrote {count} rows to {table}")


def start_tracked_run(
    workflow: AgentWorkflow, agent_name: str, project_root: Path | None
) -> tuple[RunTracker, str]:
    """Start a run in the run history, hand its id to the workflow, and open its log files."""
    run_dir = sandbox.run_dir(
        Path(workflow.services.core.action_runner.get_action_folder(agent_name))
    )
    artefact_dir = run_dir / "artefact" if sandbox.is_active() else None
    tracker = RunTracker(artefact_dir=artefact_dir, project_root=project_root)
    run_id = tracker.start_workflow_run(
        workflow_id=agent_name,
        workflow_name=agent_name,
        actions_total=len(workflow.execution_order),
    )

    workflow.services.core.action_executor.run_tracker = tracker
    workflow.services.core.action_executor.run_id = run_id
    # Re-populate now that `run_id` exists; strategies read this to build
    # the runtime `workflow` namespace (`{{ workflow.name }}`, `{{ workflow.run_id }}`).
    from agent_actions.prompt.context.scope_application import build_workflow_metadata

    workflow.services.core.action_runner.workflow_metadata = build_workflow_metadata(
        name=agent_name, run_id=run_id
    )

    LoggerFactory.initialize(
        output_dir=run_dir,
        workflow_name=agent_name,
        invocation_id=run_id,
        force=True,
        new_run=True,
    )
    return tracker, run_id


class RunCommand:
    def __init__(self, args: RunCommandArgs, sleep: Callable[[float], None] = time.sleep):
        self.args = args
        self.agent_name = Path(args.agent).stem
        self._sleep = sleep
        self._open_batches: list[str] = []

    def _determine_execution_mode(self, workflow: AgentWorkflow) -> bool:
        mode = getattr(self.args, "execution_mode", "auto")

        if mode == "parallel":
            click.echo("🔀 Using parallel execution (--execution-mode parallel)...")
            return True
        if mode == "sequential":
            click.echo("Using sequential execution (--execution-mode sequential)...")
            return False
        # mode == 'auto': let the workflow decide
        if workflow.services.core.action_level_orchestrator.should_use_parallel_execution():
            click.echo("🔀 Using parallel execution (auto-detected)...")
            return True

        click.echo("Using sequential execution...")
        return False

    def _run_workflow_execution(self, workflow: AgentWorkflow, use_parallel: bool) -> None:
        if use_parallel:
            asyncio.run(workflow.async_run(concurrency_limit=self.args.concurrency_limit))
        else:
            workflow.run()

    def execute(
        self,
        project_root: Path | None = None,
        holding_the_lock: Callable[[], AbstractContextManager[object]] | None = None,
    ) -> None:
        """Run the workflow inside *holding_the_lock*, which is entered once the run lock is held.

        It exits however the run ends, before the lock is released; it is not entered when
        the lock is refused.
        """
        click.echo(f"Starting agent run for: {self.args.agent}")

        if project_root is not None:
            from agent_actions.config.paths import PathManager
            from agent_actions.utils.path_utils import set_path_manager

            set_path_manager(PathManager(project_root=project_root))

        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.args.agent, project_root=project_root
        )
        ended = False
        # Before anything loads, clears or submits: `--fresh` clears the store inside
        # load_workflow, so a later lock would wipe a run in progress before refusing.
        try:
            with (
                hold_run_lock(paths.io_dir, self.agent_name),
                holding_the_lock() if holding_the_lock is not None else nullcontext(),
            ):
                started = time.monotonic()
                if self.args.refresh_input:
                    self._refresh_input(paths)
                outcome = self._run_holding_the_lock(paths, project_root)
                if self.args.wait:
                    outcome = self._wait_for_batches(outcome, paths, project_root, started)
                ended = True
        except ProviderQuotaStop as stop:
            report_quota_stop(stop)
            outcome = RunOutcome.QUOTA_STOP
        finally:
            if self.args.refresh_input:
                from agent_actions.input.loaders.database_source import forget_refresh_request

                # The request is process-wide; a later run in this process did not ask.
                forget_refresh_request()
            report_scenario(only_after_calls=not ended)

        if EXIT_CODES[outcome] != EXIT_SUCCESS:
            raise SystemExit(EXIT_CODES[outcome])

    def _wait_for_batches(
        self,
        outcome: RunOutcome,
        paths: ProjectPaths,
        project_root: Path | None,
        started: float,
    ) -> RunOutcome:
        """Run again, as a second `agac run` does, until no batch is open or the time is up.

        The time limit counts from *started*, before the first pass.
        """
        timeout = self.args.wait_timeout
        deadline = None if timeout is None else started + timeout
        while outcome is RunOutcome.PAUSED_FOR_BATCH:
            pause = self._poll_seconds()
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop_waiting(started)
                    break
                pause = min(pause, remaining)
            if pause > 0:
                click.echo(f"Waiting {pause:g}s before checking the batch job(s) again...")
                self._sleep(pause)
            else:
                click.echo("Checking the batch job(s) again...")
            if deadline is not None and time.monotonic() >= deadline:
                self._stop_waiting(started)
                break
            outcome = self._run_holding_the_lock(paths, project_root, resuming=True)
        if outcome is RunOutcome.PAUSED:
            click.echo(
                "--wait has no batch to wait for: the run stopped before every action ended."
            )
        return outcome

    def _poll_seconds(self) -> float:
        """Seconds between two passes: ``--poll`` when given, else the default of the run."""
        if self.args.poll is not None:
            return self.args.poll
        return sandbox.wait_between_passes() if sandbox.is_active() else DEFAULT_POLL_SECONDS

    def _stop_waiting(self, started: float) -> None:
        click.echo(
            f"Stopped waiting after {time.monotonic() - started:.0f}s: batch "
            f"job(s) still open for: {', '.join(self._open_batches)}. Run again "
            "to check them and continue: "
            f"agac run -w {self.args.agent}{sandbox.run_flags()} --wait"
        )

    def _run_holding_the_lock(
        self, paths: ProjectPaths, project_root: Path | None, *, resuming: bool = False
    ) -> RunOutcome:
        """One pass over the workflow; *resuming* is a later pass, which clears nothing."""
        with PromptLoader.record_loads() as prompt_files:
            try:
                workflow = load_workflow(
                    self.agent_name,
                    paths,
                    project_root,
                    sends_requests=True,
                    user_code_path=str(self.args.user_code) if self.args.user_code else None,
                    use_tools=self.args.use_tools,
                    fresh=self.args.fresh and not resuming,
                    rerun=() if resuming else self.args.rerun,
                    verify_keys=self.args.verify_keys and not resuming,
                    record_limit=self.args.record_limit,
                    file_limit=self.args.file_limit,
                )
            finally:
                PromptValidator().validate(prompt_files)

        check_declared_outputs(workflow, project_root)
        tracker, run_id = start_tracked_run(workflow, self.agent_name, project_root)

        outcome = RunOutcome.FAILED
        error_message = None

        try:
            use_parallel = self._determine_execution_mode(workflow)
            self._run_workflow_execution(workflow, use_parallel)
            state_mgr = workflow.services.core.state_manager
            outcome = classify_outcome(state_mgr, workflow.execution_order)
            self._open_batches = state_mgr.get_batch_submitted_actions(workflow.execution_order)
            self._report(outcome, workflow)
            if sandbox.is_active():
                click.echo(
                    "SANDBOX run: no model was called. Read its results with --sandbox, "
                    f"such as agac records -w {self.args.agent} --sandbox"
                )
            if outcome in (RunOutcome.SUCCESS, RunOutcome.RECORD_FAILURES):
                self._write_outputs(workflow, project_root)

        except ProviderQuotaStop as stop:
            outcome = RunOutcome.QUOTA_STOP
            error_message = str(stop)
            raise
        except Exception:
            outcome = RunOutcome.FAILED
            error_message = traceback.format_exc()
            raise

        finally:
            try:
                tracker.finalize_workflow_run(
                    run_id=run_id, status=TRACKER_STATUSES[outcome], error_message=error_message
                )
            except Exception as track_error:
                logger.warning(
                    "Could not finalize workflow run tracking: %s",
                    track_error,
                    exc_info=True,
                )
                click.echo(
                    f"Warning: Could not finalize workflow run tracking: {track_error}", err=True
                )

            try:
                LoggerFactory.flush()
            except Exception as e:
                logger.debug("Failed to flush event handlers: %s", e, exc_info=True)

        return outcome

    def _write_outputs(self, workflow: AgentWorkflow, project_root: Path | None) -> None:
        write_declared_outputs(workflow, project_root, self.args.agent)

    def _refresh_input(self, paths: ProjectPaths) -> None:
        """Have the database snapshots read again this run; refused under an open batch.

        Decided before the workflow loads, from what is stored, since loading (with
        ``--rerun``) clears state. A batch answers the rows it was sent, so reading
        the query again under one would forget a record whose answer is on its way.
        ``--fresh`` discards the batches, so it is not refused.
        """
        if not self.args.fresh:
            open_batches = batches_still_open(paths.io_dir, self.agent_name)
            if open_batches:
                raise click.UsageError(
                    "--refresh-input reads the query again, but a batch is still open for "
                    f"{', '.join(open_batches)}. Run without it until the batch is collected."
                )
        from agent_actions.input.loaders.database_source import request_refresh

        request_refresh()

    def _report(self, outcome: RunOutcome, workflow: AgentWorkflow) -> None:
        """Print the sentence for *outcome*; the exit code is read from the outcome alone."""
        state_mgr = workflow.services.core.state_manager
        execution_order = workflow.execution_order

        if outcome is RunOutcome.FAILED:
            failed = state_mgr.get_failed_actions(execution_order)
            skipped = state_mgr.get_skipped_actions(execution_order)
            parts = [f"Workflow finished with failures for: {self.args.agent}"]
            parts.append(f"  Failed actions: {', '.join(failed)}")
            if skipped:
                parts.append(f"  Skipped actions: {', '.join(skipped)}")
            click.echo("\n".join(parts))
        elif outcome is RunOutcome.RECORD_FAILURES:
            partial = actions_with_record_failures(state_mgr, execution_order)
            click.echo(
                f"Workflow finished with failed or exhausted records in: {', '.join(partial)}. "
                f"See them with agac dispositions -w {self.args.agent} --quarantined"
                f"{sandbox.flag()}; repair them with agac retry -w {self.args.agent}"
                f"{sandbox.run_flags()}."
            )
        elif outcome is RunOutcome.SUCCESS:
            # All complete prints nothing more; guard-skipped actions get the sentence.
            if not state_mgr.is_workflow_complete():
                click.echo(f"Successfully completed agent run for: {self.args.agent}")
        else:
            summary = state_mgr.get_summary()
            status_parts = ", ".join(f"{k}: {v}" for k, v in summary.items())
            if outcome is RunOutcome.PAUSED_FOR_BATCH:
                batch_actions = state_mgr.get_batch_submitted_actions(execution_order)
                click.echo(
                    f"Workflow paused - batch job(s) submitted for: "
                    f"{', '.join(batch_actions)} ({status_parts}). "
                    f"Run again to check status and continue."
                )
            else:
                click.echo(
                    f"Workflow paused for: {self.args.agent} ({status_parts}). "
                    f"Run again to continue."
                )


@click.command()
@workflow_option()
@sandbox_option(
    help=(
        "Answer every LLM action with the offline mock, agac-provider, and keep the "
        "output apart from real runs. No API key is needed and no model is called"
    ),
    note=(
        "the offline mock answers every LLM action. The output goes to agent_io/sandbox/ "
        "and agent_io/store/<workflow>.sandbox.db"
    ),
)
@scenario_option()
@click.option(
    "-u",
    "--user-code",
    required=False,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to the user's code folder containing UDFs",
)
@click.option("--use-tools", is_flag=True, help="Enable tool usage for actions")
@click.option(
    "--execution-mode",
    "-e",
    type=click.Choice(["auto", "parallel", "sequential"], case_sensitive=False),
    default="auto",
    help="Execution mode: 'auto' (detect based on workflow), 'parallel', or 'sequential'",
)
@click.option(
    "--concurrency-limit",
    type=click.IntRange(min=1, max=50),
    default=5,
    help="Maximum number of actions to run concurrently (default: 5, range: 1-50)",
)
@click.option(
    "--record-limit",
    type=click.IntRange(min=1),
    default=None,
    help=(
        "Cap each action at this many records per input file, whatever the workflow "
        "config sets. Takes precedence over AGAC_RECORD_LIMIT."
    ),
)
@click.option(
    "--file-limit",
    type=click.IntRange(min=1),
    default=None,
    help=(
        "Stop each action after this many input files, whatever the workflow "
        "config sets. Counts files the action got through, so one that fails "
        "does not spend the budget. Takes precedence over AGAC_FILE_LIMIT."
    ),
)
@click.option(
    "--fresh",
    is_flag=True,
    default=False,
    help="Clear stored results and status before execution (useful after failed runs)",
)
@click.option(
    "--refresh-input",
    is_flag=True,
    default=False,
    help=(
        "Read a database data source again instead of its stored snapshot. Rows "
        "added or changed since are answered; the rest keep their answers."
    ),
)
@click.option(
    "--rerun",
    metavar="ACTION",
    multiple=True,
    help=(
        "Answer every record of ACTION and of every action that reads it again, under "
        "the config as it is now. Give it more than once to rerun several actions in one "
        "run. Other actions keep their answers. A config edit alone re-runs nothing"
    ),
)
@click.option(
    "--where",
    metavar="EXPRESSION",
    default=None,
    help=(
        "With one --rerun ACTION: answer again only the records of ACTION that this guard "
        "expression matches, there and at what reads it. Every other record keeps its "
        "answers. It reads the fields ACTION stored, e.g. 'classify.label == \"other\"'"
    ),
)
@click.option(
    "--records",
    metavar="FILE",
    default=None,
    type=click.Path(dir_okay=False),
    help=(
        "With one --rerun ACTION: answer again only the records FILE lists, one "
        "source_guid a line. With --where too, a record must be listed and match"
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="With --where / --records: print the count and the ids, and call no model",
)
@click.option(
    "--verify-keys",
    is_flag=True,
    default=False,
    help="Verify API keys by probing vendor endpoints, and declared endpoints with one "
    "structured-output request, before execution",
)
@click.option(
    "--wait",
    is_flag=True,
    default=False,
    help=(
        "While the run is paused for a batch, wait and run again until no batch is open, "
        "then exit with the code of the final status"
    ),
)
@click.option(
    "--poll",
    type=click.IntRange(min=1),
    default=None,
    metavar="SECONDS",
    help=(
        "With --wait: whole seconds between two checks of the batch job(s), at least 1 "
        f"(default: {DEFAULT_POLL_SECONDS}; with --sandbox: no wait, or up to 1 second "
        "while the scenario holds a batch for complete_after_seconds)"
    ),
)
@click.option(
    "--wait-timeout",
    type=click.FloatRange(min=0),
    default=None,
    metavar="SECONDS",
    help=(
        "With --wait: stop waiting this many seconds after the run started and exit 4, "
        "leaving the batch job(s) open for the next run (default: no limit)"
    ),
)
@handles_user_errors("run")
@requires_project
def run(
    agent: str,
    user_code: str | None,
    use_tools: bool,
    execution_mode: str = "auto",
    concurrency_limit: int = 5,
    record_limit: int | None = None,
    file_limit: int | None = None,
    fresh: bool = False,
    refresh_input: bool = False,
    rerun: tuple[str, ...] = (),
    where: str | None = None,
    records: str | None = None,
    dry_run: bool = False,
    verify_keys: bool = False,
    wait: bool = False,
    poll: int | None = None,
    wait_timeout: float | None = None,
    project_root: Path | None = None,
) -> None:
    """Run agents with a specified agent configuration.

    \b
    Exit codes: 0 success, 1 failed, 3 finished with failed or exhausted
    records, 4 paused: a batch is open, or the run stopped before every
    action ended, 5 stopped by a provider's quota or billing.

    \b
    Examples:
        agac run -a my_agent
        agac run -a my_agent --execution-mode parallel
        agac run -a my_agent --fresh
        agac run -a my_agent --refresh-input
        agac run -a my_agent --rerun classify
        agac run -a my_agent --rerun classify --rerun summarize
        agac run -a my_agent --rerun classify --where 'classify.label == "other"'
        agac run -a my_agent --rerun write --records ids.txt --dry-run
        agac run -a my_agent --record-limit 2 --file-limit 1
        agac run -a my_agent --wait --poll 60 --wait-timeout 86400
        agac run -a my_agent --sandbox
    """
    if not wait:
        for given, flag in ((poll, "--poll"), (wait_timeout, "--wait-timeout")):
            if given is not None:
                raise click.UsageError(f"{flag} sets how --wait waits, and --wait was not given.")
    args = RunCommandArgs(
        agent=agent,
        user_code=Path(user_code) if user_code else None,
        use_tools=use_tools,
        execution_mode=cast(Literal["auto", "parallel", "sequential"], execution_mode),
        concurrency_limit=concurrency_limit,
        record_limit=record_limit,
        file_limit=file_limit,
        fresh=fresh,
        refresh_input=refresh_input,
        rerun=rerun,
        where=where,
        records=records,
        dry_run=dry_run,
        verify_keys=verify_keys,
        wait=wait,
        poll=poll,
        wait_timeout=wait_timeout,
    )
    if where is not None or records is not None or dry_run:
        rerun_selected_records(args, project_root)
        return
    command = RunCommand(args)
    command.execute(project_root=project_root)


def rerun_selected_records(args: RunCommandArgs, project_root: Path | None) -> None:
    """`--rerun ACTION --where/--records`: answer the matching records again, and no other.

    Runs on the retry path, which narrows a run to named records and carries every
    other record's stored row and disposition through each rewritten file.
    """
    if args.where is None and args.records is None:
        raise click.UsageError("--dry-run shows what --where or --records selects; give one.")
    if len(args.rerun) != 1:
        raise click.UsageError(
            "--where and --records choose records of one action: give exactly one --rerun ACTION."
        )
    refused = {
        "--fresh": args.fresh,
        "--refresh-input": args.refresh_input,
        "--record-limit": args.record_limit is not None,
        "--file-limit": args.file_limit is not None,
    }
    for flag, given in refused.items():
        if given:
            raise click.UsageError(
                f"{flag} does not go with --where / --records: a filtered rerun answers "
                "the records it names and leaves every other record as it is."
            )
    # Deferred: retry imports this module.
    from agent_actions.cli.args import RetryCommandArgs
    from agent_actions.cli.rerun_selection import (
        RecordFilter,
        read_record_ids,
        refuse_an_expression_that_does_not_parse,
    )
    from agent_actions.cli.retry import RetryCommand

    if args.where is not None:
        refuse_an_expression_that_does_not_parse(args.where)
    record_filter = RecordFilter(
        where=args.where,
        record_ids=read_record_ids(args.records) if args.records is not None else None,
        records_from=args.records,
    )
    retry_args = RetryCommandArgs(
        agent=args.agent, from_action=args.rerun[0], dry_run=args.dry_run
    )
    try:
        RetryCommand(retry_args, record_filter).execute(project_root=project_root)
    except SystemExit as stopped:
        paused = stopped.code == EXIT_CODES[RunOutcome.PAUSED_FOR_BATCH]
        if not args.wait or args.dry_run or not paused:
            raise
        # The batch holds only the selected records, and a plain run collects it.
        waiting = args.model_copy(update={"rerun": (), "where": None, "records": None})
        RunCommand(waiting).execute(project_root=project_root)

"""Run command for the Agent Actions CLI."""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import click

from agent_actions.cli.args import DEFAULT_POLL_SECONDS, RunCommandArgs
from agent_actions.cli.cli_decorators import (
    handles_user_errors,
    requires_project,
    workflow_option,
)
from agent_actions.cli.exit_codes import (
    EXIT_CODES,
    EXIT_SUCCESS,
    TRACKER_STATUSES,
    RunOutcome,
    actions_with_record_failures,
    classify_outcome,
)
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPaths, ProjectPathsFactory
from agent_actions.logging.factory import LoggerFactory
from agent_actions.prompt.handler import PromptLoader
from agent_actions.storage.run_lock import hold_run_lock
from agent_actions.tooling.docs.run_tracker import RunTracker
from agent_actions.validation.prompt_validator import PromptValidator

if TYPE_CHECKING:
    from agent_actions.workflow.coordinator import AgentWorkflow

logger = logging.getLogger(__name__)


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

    def execute(self, project_root: Path | None = None) -> None:
        click.echo(f"Starting agent run for: {self.args.agent}")

        if project_root is not None:
            from agent_actions.config.paths import PathManager
            from agent_actions.utils.path_utils import set_path_manager

            set_path_manager(PathManager(project_root=project_root))

        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.args.agent, project_root=project_root
        )
        # Before anything loads, clears or submits: `--fresh` clears the store inside
        # load_workflow, so a later lock would wipe a run in progress before refusing.
        with hold_run_lock(paths.io_dir, self.agent_name):
            outcome = self._run_holding_the_lock(paths, project_root)
            if self.args.wait:
                outcome = self._wait_for_batches(outcome, paths, project_root)

        if EXIT_CODES[outcome] != EXIT_SUCCESS:
            raise SystemExit(EXIT_CODES[outcome])

    def _wait_for_batches(
        self, outcome: RunOutcome, paths: ProjectPaths, project_root: Path | None
    ) -> RunOutcome:
        """Run again, as a second `agac run` does, until no batch is open or the time is up."""
        timeout = self.args.wait_timeout
        deadline = None if timeout is None else time.monotonic() + timeout
        while outcome is RunOutcome.PAUSED_FOR_BATCH:
            pause = self.args.poll
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    click.echo(
                        f"Stopped waiting after {timeout:g}s: batch job(s) still open for: "
                        f"{', '.join(self._open_batches)}. Run again to check them and "
                        f"continue: agac run -a {self.args.agent} --wait"
                    )
                    break
                pause = min(pause, remaining)
            click.echo(f"Waiting {pause:g}s before checking the batch job(s) again...")
            self._sleep(pause)
            outcome = self._run_holding_the_lock(paths, project_root, resuming=True)
        return outcome

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

        tracker = RunTracker(project_root=project_root)
        run_id = tracker.start_workflow_run(
            workflow_id=self.agent_name,
            workflow_name=self.agent_name,
            actions_total=len(workflow.execution_order),
        )

        workflow.services.core.action_executor.run_tracker = tracker
        workflow.services.core.action_executor.run_id = run_id
        # Re-populate now that `run_id` exists; strategies read this to build
        # the runtime `workflow` namespace (`{{ workflow.name }}`, `{{ workflow.run_id }}`).
        from agent_actions.prompt.context.scope_application import build_workflow_metadata

        workflow.services.core.action_runner.workflow_metadata = build_workflow_metadata(
            name=self.agent_name, run_id=run_id
        )

        agent_folder = workflow.services.core.action_runner.get_action_folder(self.agent_name)
        LoggerFactory.initialize(
            output_dir=agent_folder,
            workflow_name=self.agent_name,
            invocation_id=run_id,
            force=True,
            new_run=True,
        )

        outcome = RunOutcome.FAILED
        error_message = None

        try:
            use_parallel = self._determine_execution_mode(workflow)
            self._run_workflow_execution(workflow, use_parallel)
            state_mgr = workflow.services.core.state_manager
            outcome = classify_outcome(state_mgr, workflow.execution_order)
            self._open_batches = state_mgr.get_batch_submitted_actions(workflow.execution_order)
            self._report(outcome, workflow)

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
                f"See them with agac dispositions -a {self.args.agent} --quarantined; "
                f"repair them with agac retry -a {self.args.agent}."
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
    "--verify-keys",
    is_flag=True,
    default=False,
    help="Verify API keys by probing vendor endpoints, and declared endpoints with one structured-output request, before execution",
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
    type=click.FloatRange(min=0),
    default=None,
    metavar="SECONDS",
    help=(
        "With --wait: seconds between two checks of the batch job(s) "
        f"(default: {DEFAULT_POLL_SECONDS:g})"
    ),
)
@click.option(
    "--wait-timeout",
    type=click.FloatRange(min=0),
    default=None,
    metavar="SECONDS",
    help=(
        "With --wait: stop waiting after this many seconds and exit 4, leaving the batch "
        "job(s) open for the next run (default: no limit)"
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
    rerun: tuple[str, ...] = (),
    verify_keys: bool = False,
    wait: bool = False,
    poll: float | None = None,
    wait_timeout: float | None = None,
    project_root: Path | None = None,
) -> None:
    """Run agents with a specified agent configuration.

    \b
    Exit codes: 0 success, 1 failed, 3 finished with failed or exhausted
    records, 4 paused for a batch.

    \b
    Examples:
        agac run -a my_agent
        agac run -a my_agent --execution-mode parallel
        agac run -a my_agent --fresh
        agac run -a my_agent --rerun classify
        agac run -a my_agent --rerun classify --rerun summarize
        agac run -a my_agent --record-limit 2 --file-limit 1
        agac run -a my_agent --wait --poll 60 --wait-timeout 86400
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
        rerun=rerun,
        verify_keys=verify_keys,
        wait=wait,
        poll=DEFAULT_POLL_SECONDS if poll is None else poll,
        wait_timeout=wait_timeout,
    )
    command = RunCommand(args)
    command.execute(project_root=project_root)

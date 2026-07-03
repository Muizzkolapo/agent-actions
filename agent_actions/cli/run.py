"""Run command for the Agent Actions CLI."""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.logging.factory import LoggerFactory
from agent_actions.storage.lock import WorkflowLockHeld, workflow_lock
from agent_actions.tooling.docs.run_tracker import RunTracker
from agent_actions.validation.prompt_validator import PromptValidator
from agent_actions.validation.run_validator import RunCommandArgs

if TYPE_CHECKING:
    from agent_actions.workflow.coordinator import AgentWorkflow

logger = logging.getLogger(__name__)


class RunCommand:
    def __init__(self, args: RunCommandArgs):
        self.args = args
        self.agent_name = Path(args.agent).stem

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
        self._execute_single(project_root)

    def _execute_single(self, project_root: Path | None = None) -> str:
        click.echo(f"Starting agent run for: {self.args.agent}")

        if project_root is not None:
            from agent_actions.config.paths import PathManager
            from agent_actions.utils.path_utils import set_path_manager

            set_path_manager(PathManager(project_root=project_root))

        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.args.agent, project_root=project_root
        )
        PromptValidator().validate(paths.prompt_dir, config={"workflow_name": self.agent_name})
        workflow = load_workflow(
            self.agent_name,
            paths,
            project_root,
            user_code_path=str(self.args.user_code) if self.args.user_code else None,
            use_tools=self.args.use_tools,
            fresh=self.args.fresh,
            verify_keys=self.args.verify_keys,
        )

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
        )

        status = "FAILED"
        error_message = None
        wall_start = time.monotonic()

        try:
            use_parallel = self._determine_execution_mode(workflow)
            self._run_workflow_execution(workflow, use_parallel)

            elapsed = time.monotonic() - wall_start

            # Render execution summary
            try:
                from agent_actions.cli.renderers.execution_renderer import (
                    ExecutionRenderer,
                    build_execution_snapshot,
                )

                snapshot = build_execution_snapshot(workflow, elapsed)
                ExecutionRenderer(workflow.console).render(snapshot)
            except Exception as render_err:
                logger.warning("Execution summary render failed: %s", render_err, exc_info=True)

            state_mgr = workflow.services.core.state_manager
            execution_order = workflow.execution_order

            if state_mgr.is_workflow_complete():
                status = "SUCCESS"

            elif state_mgr.is_workflow_done():
                # All actions terminal — check if any actually failed
                if state_mgr.has_any_failed():
                    status = "FAILED"
                    failed = state_mgr.get_failed_actions(execution_order)
                    skipped = state_mgr.get_skipped_actions(execution_order)
                    parts = [f"Workflow finished with failures for: {self.args.agent}"]
                    parts.append(f"  Failed actions: {', '.join(failed)}")
                    if skipped:
                        parts.append(f"  Skipped actions: {', '.join(skipped)}")
                    click.echo("\n".join(parts))
                else:
                    # All terminal, none failed (some may be skipped by guards)
                    status = "SUCCESS"
                    click.echo(f"Successfully completed agent run for: {self.args.agent}")

            else:
                # Not all terminal — check for actual batch jobs
                batch_actions = state_mgr.get_batch_submitted_actions(execution_order)
                if batch_actions:
                    status = "PAUSED"
                    click.echo(
                        f"Workflow paused - batch job(s) submitted for: "
                        f"{', '.join(batch_actions)}. "
                        f"Run again to check status and continue."
                    )
                else:
                    status = "PAUSED"
                    summary = state_mgr.get_summary()
                    status_parts = ", ".join(f"{k}: {v}" for k, v in summary.items())
                    click.echo(
                        f"Workflow paused for: {self.args.agent} ({status_parts}). "
                        f"Run again to continue."
                    )

        except Exception:
            status = "FAILED"
            error_message = traceback.format_exc()
            raise

        finally:
            try:
                tracker.finalize_workflow_run(
                    run_id=run_id, status=status, error_message=error_message
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

        if status == "FAILED":
            raise SystemExit(1)

        return status


@click.command()
@click.option(
    "-a", "--agent", required=True, help="Agent configuration file name without path or extension"
)
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
    "--fresh",
    is_flag=True,
    default=False,
    help="Clear stored results and status before execution (useful after failed runs)",
)
@click.option(
    "--verify-keys",
    is_flag=True,
    default=False,
    help="Verify API keys are valid by probing vendor endpoints before execution",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help=(
        "Bypass the advisory concurrency lock. Use only if you understand that "
        "two parallel runs double-execute every action and double the LLM cost."
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
    fresh: bool = False,
    verify_keys: bool = False,
    force: bool = False,
    project_root: Path | None = None,
) -> None:
    """
    Run agents with a specified agent configuration.

    The run command executes agent workflows based on the specified configuration.
    It handles the entire lifecycle from loading configuration to executing
    the workflow and processing results.

    Examples:
        agac run -a my_agent
        agac run -a my_agent --execution-mode parallel
        agac run -a my_agent --fresh
    """
    args = RunCommandArgs(
        agent=agent,
        user_code=Path(user_code) if user_code else None,
        use_tools=use_tools,
        execution_mode=cast(Literal["auto", "parallel", "sequential"], execution_mode),
        concurrency_limit=concurrency_limit,
        fresh=fresh,
        verify_keys=verify_keys,
    )
    command = RunCommand(args)

    if force:
        command.execute(project_root=project_root)
        return

    # Advisory lock (VIOL-0045): one `agac run` writer per workflow per machine.
    # Wraps the whole run — releasing mid-run would reopen the double-execute
    # window. The lock keys on the config name (`-a`), so repeat invocations of
    # the same workflow contend; the OS releases it if the process is killed.
    store_dir = project_root / "agent_io" / "store"
    try:
        with workflow_lock(store_dir, command.agent_name):
            command.execute(project_root=project_root)
    except WorkflowLockHeld as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc

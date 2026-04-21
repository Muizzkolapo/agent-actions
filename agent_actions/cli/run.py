"""Run command for the Agent Actions CLI."""

import asyncio
import logging
import time
import traceback
from pathlib import Path
from typing import Literal, cast

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.project_paths import ProjectPathsFactory, find_config_file
from agent_actions.logging.factory import LoggerFactory
from agent_actions.prompt.renderer import ConfigRenderingService
from agent_actions.tooling.docs.run_tracker import RunTracker
from agent_actions.validation.prompt_validator import PromptValidator
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.models import WorkflowPaths, WorkflowRuntimeConfig

logger = logging.getLogger(__name__)
from agent_actions.validation.run_validator import RunCommandArgs


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
        if self.args.downstream or self.args.upstream:
            self._execute_chain(project_root)
            return

        self._execute_single(project_root)

    def _execute_chain(self, project_root: Path | None = None) -> None:
        """Execute a chain of workflows based on --downstream/--upstream flags."""
        from agent_actions.workflow.orchestrator import WorkflowOrchestrator

        effective_root = project_root or Path.cwd()
        orchestrator = WorkflowOrchestrator(effective_root)

        direction: Literal["downstream", "upstream", "full"]
        if self.args.upstream and self.args.downstream:
            direction = "full"
        elif self.args.downstream:
            direction = "downstream"
        else:
            direction = "upstream"

        plan = orchestrator.resolve_execution_plan(self.agent_name, direction)
        click.echo(f"Execution plan ({direction}): {' -> '.join(plan)}")

        scope_map = orchestrator.build_upstream_scope_map(plan)

        for i, workflow_name in enumerate(plan):
            click.echo(f"\n--- Running workflow: {workflow_name} ---")
            # Empty scope list means no upstreams in plan (e.g. the target itself) — pass None
            scope = scope_map.get(workflow_name) or None
            chain_args = self.args.model_copy(
                update={
                    "agent": workflow_name,
                    "downstream": False,
                    "upstream": False,
                    "upstream_scope": scope,
                }
            )
            status = RunCommand(chain_args)._execute_single(project_root=project_root)

            if status == "PAUSED":
                for deferred_name in plan[i + 1 :]:
                    click.echo(
                        f"Downstream workflow '{deferred_name}' deferred "
                        f"— waiting for parent batch to complete"
                    )
                break

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
        filename = f"{self.agent_name}.yml"
        full_path = find_config_file(
            self.agent_name,
            paths.agent_config_dir,
            filename,
            check_alternatives=True,
            project_root=project_root,
        )
        ConfigRenderingService().render_and_load_config(
            self.agent_name,
            full_path,
            paths.template_dir,
            paths.rendered_workflows_dir,
            project_root=project_root,
        )
        workflow = AgentWorkflow(
            WorkflowRuntimeConfig(
                paths=WorkflowPaths(
                    constructor_path=str(full_path),
                    user_code_path=str(self.args.user_code) if self.args.user_code else None,
                    default_path=str(paths.default_config_path),
                ),
                use_tools=self.args.use_tools,
                fresh=self.args.fresh,
                verify_keys=self.args.verify_keys,
                project_root=project_root,
                upstream_scope=self.args.upstream_scope,
            )
        )

        tracker = RunTracker(project_root=project_root)
        run_id = tracker.start_workflow_run(
            workflow_id=self.agent_name,
            workflow_name=self.agent_name,
            actions_total=len(workflow.execution_order),
        )

        workflow.services.core.action_executor.run_tracker = tracker
        workflow.services.core.action_executor.run_id = run_id

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
                logger.debug("Execution summary render failed: %s", render_err)

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
    "--downstream",
    is_flag=True,
    default=False,
    help="Also run all workflows that depend on this one",
)
@click.option(
    "--upstream",
    is_flag=True,
    default=False,
    help="Run all upstream workflow dependencies before this one",
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
    downstream: bool = False,
    upstream: bool = False,
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
        agac run -a my_agent --downstream
        agac run -a my_agent --upstream
    """
    args = RunCommandArgs(
        agent=agent,
        user_code=Path(user_code) if user_code else None,
        use_tools=use_tools,
        execution_mode=cast(Literal["auto", "parallel", "sequential"], execution_mode),
        concurrency_limit=concurrency_limit,
        fresh=fresh,
        verify_keys=verify_keys,
        downstream=downstream,
        upstream=upstream,
    )
    command = RunCommand(args)
    command.execute(project_root=project_root)

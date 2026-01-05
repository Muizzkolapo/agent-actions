"""
Run command for the Agent Actions CLI.

This module provides the implementation of the 'run' command,
which executes agent workflows based on configuration files.
"""

from pathlib import Path
from typing import Optional

import asyncio
import traceback
import click

from agent_actions.cli.cli_decorators import requires_project, handles_user_errors
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from agent_actions.docs.run_tracker import RunTracker
from agent_actions.errors import FileLoadError  # New modular pattern!
from agent_actions.orchestration.agent_workflow import AgentWorkflow, WorkflowConfig, WorkflowPaths
from agent_actions.prompt_generation.config_renderer import ConfigRenderer
from agent_actions.validation.prompt_validator import PromptValidator
from agent_actions.validation.run_validator import RunCommandArgs
from agent_actions.validation.preflight import (
    VendorCompatibilityValidator,
    DependencyValidator,
)


class RunCommand:
    """Implementation of the run command."""

    def __init__(self, args: RunCommandArgs):
        """
        Initialize the run command.

        Args:
            args: Pydantic model containing the command arguments.
        """
        self.args = args
        self.agent_name = Path(args.agent).stem

    def _find_config_file(self, config_dir: Path, filename: str) -> Path:
        """Find the configuration file."""
        full_path = config_dir / filename
        if not full_path.exists():
            # Check for alternative locations
            parent_dir = config_dir.parent
            alternatives_checked = [
                parent_dir / filename,
                Path.cwd() / filename,
                Path.cwd() / "config" / filename,
            ]
            existing_alternatives = [str(p) for p in alternatives_checked if p.exists()]

            raise FileLoadError(
                "Configuration file not found",
                context={
                    "file_path": str(full_path),
                    "config_dir": str(config_dir),
                    "filename": filename,
                    "agent_name": self.agent_name,
                    "alternatives_checked": [str(p) for p in alternatives_checked],
                    "found_alternatives": existing_alternatives if existing_alternatives else None,
                    "suggestion": (
                        f"File not found at {full_path}. "
                        f"Check if the file exists or use an absolute path."
                        + (
                            f" Found similar file at: {existing_alternatives[0]}"
                            if existing_alternatives
                            else ""
                        )
                    ),
                },
            )
        return full_path

    def _determine_execution_mode(self, workflow: AgentWorkflow) -> bool:
        """Determine if parallel execution should be used."""
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
        """Run the actual workflow execution."""
        if use_parallel:
            asyncio.run(workflow.async_run(concurrency_limit=self.args.concurrency_limit))
        else:
            workflow.run()

    def execute_validation_only(self, static_typing: bool = True) -> None:
        """
        Execute pre-flight validation only, without running the workflow.

        This validates:
        - Workflow configuration
        - Agent configurations (vendor compatibility)
        - Dependencies (circular detection)
        - Template variables (if possible without data)
        - Static type checking (field references)

        Args:
            static_typing: Whether to run static type checking (default: True)

        Exits with code 0 if valid, 1 if errors found.
        """
        import sys

        click.echo(f"Running pre-flight validation for: {self.args.agent}")
        click.echo("Setting up project paths...")

        paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.args.agent)
        PromptValidator().validate(paths.prompt_dir)

        filename = f"{self.agent_name}.yml"
        full_path = self._find_config_file(paths.agent_config_dir, filename)

        click.echo("Rendering and loading configuration...")
        ConfigRenderer.render_and_load_config(
            self.agent_name, full_path, paths.template_dir, paths.rendered_workflows_dir
        )

        click.echo("Loading workflow configuration...")
        workflow = AgentWorkflow(
            WorkflowConfig(
                paths=WorkflowPaths(
                    constructor_path=str(full_path),
                    user_code_path=str(self.args.user_code) if self.args.user_code else None,
                    default_path=str(paths.default_config_path),
                ),
                use_tools=self.args.use_tools,
                run_upstream=self.args.upstream,
                run_downstream=self.args.downstream,
            )
        )

        click.echo("\nRunning pre-flight validation...")
        click.echo("-" * 50)

        errors = []
        warnings = []

        # 1. Validate vendor compatibility for each agent
        vendor_validator = VendorCompatibilityValidator()
        for agent_name, agent_config in workflow.agent_configs.items():
            if not vendor_validator.validate_vendor_config(agent_config, agent_name):
                for issue in vendor_validator.get_issues():
                    if issue.issue_type == "error":
                        errors.append(f"[{agent_name}] {issue.message}")
                    else:
                        warnings.append(f"[{agent_name}] {issue.message}")

        # 2. Validate dependencies
        dep_validator = DependencyValidator()
        if not dep_validator.validate_workflow(
            {"agents": workflow.agent_configs},
            workflow.agent_configs,
        ):
            for issue in dep_validator.get_issues():
                if issue.issue_type == "error":
                    errors.append(f"[dependency] {issue.message}")
                else:
                    warnings.append(f"[dependency] {issue.message}")

        # 3. Static type checking (field references)
        if static_typing:
            click.echo("\nRunning static type checking...")
            from agent_actions.validation.static_analyzer import WorkflowStaticAnalyzer

            # Build workflow config dict from agent_configs
            workflow_config = {
                "actions": [
                    {**config, "name": name} for name, config in workflow.agent_configs.items()
                ]
            }

            analyzer = WorkflowStaticAnalyzer(workflow_config)
            static_result = analyzer.analyze()

            for error in static_result.errors:
                errors.append(f"[static] {error.format_message()}")

            for warning in static_result.warnings:
                warnings.append(f"[static] {warning.format_message()}")

        # 4. Report results
        click.echo("")
        if errors:
            click.echo(click.style("VALIDATION FAILED", fg="red", bold=True))
            click.echo(f"\n{len(errors)} error(s) found:\n")
            for error in errors:
                click.echo(click.style(f"  ERROR: {error}", fg="red"))
        else:
            click.echo(click.style("VALIDATION PASSED", fg="green", bold=True))

        if warnings:
            click.echo(f"\n{len(warnings)} warning(s):\n")
            for warning in warnings:
                click.echo(click.style(f"  WARNING: {warning}", fg="yellow"))

        click.echo("")
        click.echo("-" * 50)

        if errors:
            click.echo("Pre-flight validation failed. Fix errors before running workflow.")
            sys.exit(1)
        else:
            click.echo("Pre-flight validation passed. Workflow is ready to run.")
            sys.exit(0)

    def execute(self) -> None:
        """
        Execute the run command.

        Raises:
            Various exceptions depending on the stage that fails
        """
        click.echo(f"Starting agent run for: {self.args.agent}")
        click.echo("Setting up project paths...")
        paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.args.agent)
        PromptValidator().validate(paths.prompt_dir)
        filename = f"{self.agent_name}.yml"
        full_path = self._find_config_file(paths.agent_config_dir, filename)
        click.echo("Rendering and loading configuration...")
        ConfigRenderer.render_and_load_config(
            self.agent_name, full_path, paths.template_dir, paths.rendered_workflows_dir
        )
        click.echo("Initializing agent workflow...")
        workflow = AgentWorkflow(
            WorkflowConfig(
                paths=WorkflowPaths(
                    constructor_path=str(full_path),
                    user_code_path=str(self.args.user_code) if self.args.user_code else None,
                    default_path=str(paths.default_config_path),
                ),
                use_tools=self.args.use_tools,
                run_upstream=self.args.upstream,
                run_downstream=self.args.downstream,
            )
        )

        # Initialize run tracker
        tracker = RunTracker()
        run_id = tracker.start_workflow_run(
            workflow_id=self.agent_name,
            workflow_name=self.agent_name,
            actions_total=len(workflow.execution_order),
        )

        # Pass tracker and run_id to executor for action-level tracking
        workflow.services.core.agent_executor.run_tracker = tracker
        workflow.services.core.agent_executor.run_id = run_id

        click.echo("Starting workflow execution...")

        # Track execution state
        status = "FAILED"  # Default to failed, update on success
        error_message = None

        try:
            use_parallel = self._determine_execution_mode(workflow)
            self._run_workflow_execution(workflow, use_parallel)

            # Determine final status
            if workflow.services.core.state_manager.is_workflow_complete():
                status = "SUCCESS"
                click.echo(f"Successfully completed agent run for: {self.args.agent}")
            else:
                status = "PAUSED"
                click.echo(
                    "Workflow paused - batch job(s) submitted. "
                    "Run again to check status and continue."
                )

        except Exception:
            status = "FAILED"
            # Capture full traceback for better debugging (like Airflow)
            error_message = traceback.format_exc()
            raise  # Re-raise to maintain existing error handling

        finally:
            # Finalize run tracking
            try:
                tracker.finalize_workflow_run(
                    run_id=run_id, status=status, error_message=error_message
                )
            except Exception as track_error:
                # Don't fail the workflow if tracking fails
                click.echo(
                    f"Warning: Could not finalize workflow run tracking: {track_error}", err=True
                )


@click.command()
@click.option(
    "-a", "--agent", required=True, help="Agent configuration file name without path or extension"
)
@click.option(
    "-u",
    "--user_code",
    required=False,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to the user's code folder containing UDFs",
)
@click.option("--use-tools", is_flag=True, help="Enable tool usage for agents")
@click.option("--force", is_flag=True, help="Force execution even if validation warnings occur")
@click.option(
    "--execution-mode",
    "-e",
    type=click.Choice(["auto", "parallel", "sequential"], case_sensitive=False),
    default="auto",
    help="Execution mode: 'auto' (detect based on workflow), 'parallel', or 'sequential'",
)
@click.option(
    "--concurrency-limit",
    type=int,
    default=5,
    help="Maximum number of agents to run concurrently (default: 5, range: 1-50)",
)
@click.option("--upstream", is_flag=True, help="Recursively execute upstream dependent workflows")
@click.option(
    "--downstream",
    is_flag=True,
    help="Execute all downstream workflows that depend on this workflow",
)
@click.option(
    "--validate-only",
    "-v",
    is_flag=True,
    help="Run pre-flight validation only, without executing the workflow",
)
@click.option(
    "--static-typing/--no-static-typing",
    default=True,
    help="Enable/disable static type checking of field references (default: enabled)",
)
@handles_user_errors("run")
@requires_project
# Click decorators require explicit params
def run(
    agent: str,
    user_code: Optional[str],
    use_tools: bool,
    force: bool = False,
    execution_mode: str = "auto",
    concurrency_limit: int = 5,
    upstream: bool = False,
    downstream: bool = False,
    validate_only: bool = False,
    static_typing: bool = True,
) -> None:
    """
    Run agents with a specified agent configuration.

    The run command executes agent workflows based on the specified configuration.
    It handles the entire lifecycle from loading configuration to executing
    the workflow and processing results.

    Examples:
        agent-actions run -a my_agent
        agent-actions run -a my_agent --upstream
        agent-actions run -a my_agent --downstream
        agent-actions run -a my_agent --upstream --downstream
    """
    # Let @handles_user_errors decorator handle all exceptions
    # for consistent error formatting
    args = RunCommandArgs(
        agent=agent,
        user_code=user_code,
        use_tools=use_tools,
        force=force,
        execution_mode=execution_mode,
        concurrency_limit=concurrency_limit,
        upstream=upstream,
        downstream=downstream,
    )
    command = RunCommand(args)

    # Handle validate-only mode
    if validate_only:
        command.execute_validation_only(static_typing=static_typing)
    else:
        command.execute()

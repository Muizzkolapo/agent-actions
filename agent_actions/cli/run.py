"""
Run command for the Agent Actions CLI.

This module provides the implementation of the 'run' command,
which executes agent workflows based on configuration files.
"""
from pathlib import Path
from typing import Optional

import asyncio
import click

from agent_actions.cli.cli_decorators import requires_project, handles_user_errors
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from agent_actions.docs.run_tracker import RunTracker
from agent_actions.errors import FileLoadError  # New modular pattern!
from agent_actions.orchestration.agent_workflow import AgentWorkflow
from agent_actions.prompt_generation.config_renderer import ConfigRenderer
from agent_actions.validation.prompt_validator import PromptValidator
from agent_actions.validation.run_validator import RunCommandArgs

class RunCommand:  # pylint: disable=too-few-public-methods
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
                Path.cwd() / 'config' / filename
            ]
            existing_alternatives = [str(p) for p in alternatives_checked if p.exists()]

            raise FileLoadError(
                'Configuration file not found',
                context={
                    'file_path': str(full_path),
                    'config_dir': str(config_dir),
                    'filename': filename,
                    'agent_name': self.agent_name,
                    'alternatives_checked': [str(p) for p in alternatives_checked],
                    'found_alternatives': existing_alternatives if existing_alternatives else None,
                    'suggestion': (
                        f"File not found at {full_path}. "
                        f"Check if the file exists or use an absolute path."
                        + (f" Found similar file at: {existing_alternatives[0]}"
                           if existing_alternatives else "")
                    )
                }
            )
        return full_path

    def _determine_execution_mode(self, workflow: AgentWorkflow) -> bool:
        """Determine if parallel execution should be used."""
        if hasattr(self.args, 'parallel') and self.args.parallel:
            click.echo(
                '🔀 Using parallel execution (forced via --parallel flag)...'
            )
            return True
        if hasattr(self.args, 'no_parallel') and self.args.no_parallel:
            click.echo(
                'Using sequential execution (forced via --no-parallel flag)...'
            )
            return False
        if workflow.action_level_orchestrator.should_use_parallel_execution():
            click.echo('🔀 Using parallel execution (auto-detected)...')
            return True

        click.echo('Using sequential execution...')
        return False

    def _run_workflow_execution(self, workflow: AgentWorkflow, use_parallel: bool) -> None:
        """Run the actual workflow execution."""
        if use_parallel:
            asyncio.run(
                workflow.async_run(
                    concurrency_limit=self.args.concurrency_limit
                )
            )
        else:
            workflow.run()

    def execute(self) -> None:
        """
        Execute the run command.

        Raises:
            Various exceptions depending on the stage that fails
        """
        click.echo(f'Starting agent run for: {self.args.agent}')
        click.echo('Setting up project paths...')
        paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.args.agent)
        PromptValidator().validate(paths.prompt_dir)
        filename = f'{self.agent_name}.yml'
        full_path = self._find_config_file(paths.agent_config_dir, filename)
        click.echo('Rendering and loading configuration...')
        ConfigRenderer.render_and_load_config(
            self.agent_name, full_path, paths.template_dir,
            paths.rendered_workflows_dir
        )
        click.echo('Initializing agent workflow...')
        workflow = AgentWorkflow(
            constructor_path=str(full_path),
            user_code_path=str(self.args.user_code) if self.args.user_code else None,
            default_path=str(paths.default_config_path),
            use_tools=self.args.use_tools,
            run_upstream=self.args.upstream
        )

        # Initialize run tracker
        tracker = RunTracker()
        run_id = tracker.start_workflow_run(
            workflow_id=self.agent_name,
            workflow_name=self.agent_name,
            actions_total=len(workflow.execution_order)
        )

        # Pass tracker and run_id to executor for action-level tracking
        workflow.agent_executor.run_tracker = tracker
        workflow.agent_executor.run_id = run_id

        click.echo('Starting workflow execution...')

        # Track execution state
        status = 'FAILED'  # Default to failed, update on success
        error_message = None

        try:
            use_parallel = self._determine_execution_mode(workflow)
            self._run_workflow_execution(workflow, use_parallel)

            # Determine final status
            if workflow.state_manager.is_workflow_complete():
                status = 'SUCCESS'
                click.echo(f'Successfully completed agent run for: {self.args.agent}')
            else:
                status = 'PAUSED'
                click.echo(
                    'Workflow paused - batch job(s) submitted. '
                    'Run again to check status and continue.'
                )

        except Exception as e:  # pylint: disable=broad-exception-caught
            status = 'FAILED'
            error_message = str(e)
            raise  # Re-raise to maintain existing error handling

        finally:
            # Finalize run tracking
            try:
                tracker.finalize_workflow_run(run_id, status, error_message)
            except Exception as track_error:  # pylint: disable=broad-exception-caught
                # Don't fail the workflow if tracking fails
                click.echo(
                    f"Warning: Could not finalize workflow run tracking: "
                    f"{track_error}",
                    err=True
                )

@click.command()
@click.option(
    '-a', '--agent', required=True,
    help='Agent configuration file name without path or extension'
)
@click.option(
    '-u', '--user_code', required=False,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to the user's code folder containing UDFs"
)
@click.option('--use-tools', is_flag=True, help='Enable tool usage for agents')
@click.option(
    '--force', is_flag=True,
    help='Force execution even if validation warnings occur'
)
@click.option(
    '--parallel', is_flag=True,
    help='Force parallel execution (overrides auto-detection)'
)
@click.option(
    '--no-parallel', is_flag=True,
    help='Force sequential execution (overrides auto-detection)'
)
@click.option(
    '--concurrency-limit', type=int, default=5,
    help='Maximum number of agents to run concurrently (default: 5, range: 1-50)'
)
@click.option(
    '--upstream', is_flag=True,
    help='Recursively execute upstream dependent workflows'
)
@handles_user_errors('run')
@requires_project
# pylint: disable=too-many-arguments,too-many-positional-arguments
# Click decorators require explicit params
def run(
    agent: str,
    user_code: Optional[str],
    use_tools: bool,
    force: bool=False,
    parallel: bool=False,
    no_parallel: bool=False,
    concurrency_limit: int=5,
    upstream: bool=False
) -> None:
    """
    Run agents with a specified agent configuration.

    The run command executes agent workflows based on the specified configuration.
    It handles the entire lifecycle from loading configuration to executing
    the workflow and processing results.

    Examples:
        agent-actions run -a my_agent
        agent-actions run -a my_agent --upstream
    """
    # Let @handles_user_errors decorator handle all exceptions
    # for consistent error formatting
    args = RunCommandArgs(
        agent=agent,
        user_code=user_code,
        use_tools=use_tools,
        force=force,
        parallel=parallel,
        no_parallel=no_parallel,
        concurrency_limit=concurrency_limit,
        upstream=upstream
    )
    command = RunCommand(args)
    command.execute()

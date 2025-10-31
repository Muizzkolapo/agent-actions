"""
Run command for the Agent Actions CLI.

This module provides the implementation of the 'run' command,
which executes agent workflows based on configuration files.
"""
import click
from pathlib import Path
from typing import Optional
from agent_actions.validation.prompt_validator import PromptValidator
from agent_actions.prompt_generation.config_renderer import ConfigRenderer
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from agent_actions.orchestration.agent_workflow import AgentWorkflow
from agent_actions.shared.exceptions import ConfigurationError, ValidationError, FileLoadError, AgentExecutionError
from agent_actions.validation.run_validator import RunCommandArgs
from agent_actions.cli.cli_decorators import requires_project

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
            raise FileLoadError('Configuration file not found', context={'file_path': str(full_path), 'config_dir': str(config_dir), 'filename': filename, 'agent_name': self.agent_name})
        return full_path

    def execute(self) -> None:
        """
        Execute the run command.
        
        Raises:
            Various exceptions depending on the stage that fails
        """
        try:
            from qanalabs.tools import validators
            click.echo('Loaded qanalabs custom validators')
        except ImportError:
            pass
        click.echo(f'Starting agent run for: {self.args.agent}')
        try:
            click.echo('Setting up project paths...')
            paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.args.agent)
            PromptValidator().validate(paths.prompt_dir)
            filename = f'{self.agent_name}.yml'
            full_path = self._find_config_file(paths.agent_config_dir, filename)
            click.echo('Rendering and loading configuration...')
            ConfigRenderer.render_and_load_config(self.agent_name, full_path, paths.template_dir, paths.rendered_workflows_dir)
            click.echo('Initializing agent workflow...')
            workflow = AgentWorkflow(constructor_path=str(full_path), user_code_path=str(self.args.user_code) if self.args.user_code else None, default_path=str(paths.default_config_path), use_tools=self.args.use_tools)
            click.echo('Starting workflow execution...')
            use_parallel = False
            if hasattr(self.args, 'parallel') and self.args.parallel:
                use_parallel = True
                click.echo('🔀 Using parallel execution (forced via --parallel flag)...')
            elif hasattr(self.args, 'no_parallel') and self.args.no_parallel:
                use_parallel = False
                click.echo('Using sequential execution (forced via --no-parallel flag)...')
            elif workflow._should_use_parallel_execution():
                use_parallel = True
                click.echo('🔀 Using parallel execution (auto-detected)...')
            else:
                click.echo('Using sequential execution...')
            if use_parallel:
                import asyncio
                asyncio.run(workflow.async_run(concurrency_limit=self.args.concurrency_limit))
            else:
                workflow.run()
            click.echo(f'Successfully completed agent run for: {self.args.agent}')
        except (ValidationError, FileLoadError, ConfigurationError, AgentExecutionError) as e:
            from agent_actions.shared.user_errors import format_user_error
            context = {'agent': self.args.agent, 'command': 'run', 'error_type': type(e).__name__}
            error_message = format_user_error(e, context)
            raise click.ClickException(error_message)
        except Exception as e:
            from agent_actions.shared.user_errors import format_user_error
            context = {'agent': self.args.agent, 'command': 'run'}
            error_message = format_user_error(e, context)
            raise click.ClickException(error_message)

@click.command()
@click.option('-a', '--agent', required=True, help='Agent configuration file name without path or extension')
@click.option('-u', '--user_code', required=False, type=click.Path(exists=True, file_okay=False, dir_okay=True), help="Path to the user's code folder containing UDFs")
@click.option('--use-tools', is_flag=True, help='Enable tool usage for agents')
@click.option('--force', is_flag=True, help='Force execution even if validation warnings occur')
@click.option('--parallel', is_flag=True, help='Force parallel execution (overrides auto-detection)')
@click.option('--no-parallel', is_flag=True, help='Force sequential execution (overrides auto-detection)')
@click.option('--concurrency-limit', type=int, default=5, help='Maximum number of agents to run concurrently (default: 5, range: 1-50)')
@requires_project
def run(agent: str, user_code: Optional[str], use_tools: bool, force: bool=False, parallel: bool=False, no_parallel: bool=False, concurrency_limit: int=5) -> None:
    """
    Run agents with a specified agent configuration.

    The run command executes agent workflows based on the specified configuration.
    It handles the entire lifecycle from loading configuration to executing 
    the workflow and processing results.

    Examples:
        agent-actions run -a my_agent
        agent-actions run -a my_agent -u ./user_code --use-tools
    """
    try:
        args = RunCommandArgs(agent=agent, user_code=user_code, use_tools=use_tools, force=force, parallel=parallel, no_parallel=no_parallel, concurrency_limit=concurrency_limit)
        command = RunCommand(args)
        command.execute()
    except ValidationError as e:
        raise click.ClickException(str(e))
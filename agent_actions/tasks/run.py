"""
Run command for the Agent Actions CLI.

This module provides the implementation of the 'run' command,
which executes agent workflows based on configuration files.
"""

import click
from pathlib import Path
from typing import Optional

from agent_actions.agents.validators.prompt_validator import PromptValidator
from agent_actions.tasks.services.config_renderer import ConfigRenderer
from agent_actions.tasks.services.project_paths_factory import ProjectPathsFactory
from agent_actions.core.graph.agent_workflow import AgentWorkflow
from agent_actions.cli.exceptions import (
    ConfigurationError, 
    ValidationError,
    FileNotFoundError,
    AgentExecutionError
)
from agent_actions.agents.validators.run_validator import RunCommandArgs

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
            raise FileNotFoundError(f"Configuration file not found at {full_path}")
        return full_path

    def execute(self) -> None:
        """
        Execute the run command.
        
        Raises:
            Various exceptions depending on the stage that fails
        """
        # Import custom validators before workflow initialization
        try:
            from qanalabs.tools import validators
            click.echo("Loaded qanalabs custom validators")
        except ImportError:
            pass  # qanalabs validators not available
        
        click.echo(f"Starting agent run for: {self.args.agent}")
        
        try:
            click.echo("Setting up project paths...")
            paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.args.agent)   
            
            # Validate prompts directory
            PromptValidator().validate(paths.prompt_dir)    
            
            filename = f"{self.agent_name}.yml"
            full_path = self._find_config_file(paths.agent_config_dir, filename)
            
            click.echo("Rendering and loading configuration...")
            ConfigRenderer.render_and_load_config(
                self.agent_name, 
                full_path, 
                paths.template_dir, 
                paths.rendered_workflows_dir
            )
            
            click.echo("Initializing agent workflow...")
            workflow = AgentWorkflow(
                constructor_path=str(full_path),
                user_code_path=str(self.args.user_code) if self.args.user_code else None,
                default_path=str(paths.default_config_path),
                use_tools=self.args.use_tools
            )
            
            click.echo("Starting workflow execution...")
            workflow.run()
            
            click.echo(f"Successfully completed agent run for: {self.args.agent}")
            
        except (ValidationError, FileNotFoundError, ConfigurationError, AgentExecutionError) as e:
            # Known errors - use user-friendly formatting
            from agent_actions.core.user_errors import format_user_error

            context = {
                'agent': self.args.agent,
                'command': 'run',
                'error_type': type(e).__name__
            }

            error_message = format_user_error(e, context)
            raise click.ClickException(error_message)

        except Exception as e:
            # Unexpected errors - still use user-friendly formatting
            from agent_actions.core.user_errors import format_user_error

            context = {
                'agent': self.args.agent,
                'command': 'run'
            }

            error_message = format_user_error(e, context)
            raise click.ClickException(error_message)

@click.command()
@click.option('-a', '--agent', required=True,
              help="Agent configuration file name without path or extension")
@click.option('-u', '--user_code', required=False, type=click.Path(exists=True, file_okay=False, dir_okay=True),
              help="Path to the user's code folder containing UDFs")
@click.option('--use-tools', is_flag=True, help="Enable tool usage for agents")
@click.option('--force', is_flag=True, help="Force execution even if validation warnings occur")
def run(agent: str, user_code: Optional[str], use_tools: bool, force: bool = False) -> None:
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
        args = RunCommandArgs(agent=agent, user_code=user_code, use_tools=use_tools, force=force)
        command = RunCommand(args)
        command.execute()
    except ValidationError as e:
        raise click.ClickException(str(e))

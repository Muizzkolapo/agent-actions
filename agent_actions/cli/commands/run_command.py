"""
Run command for the Agent Actions CLI.

This module provides the implementation of the 'run' command,
which executes agent workflows based on configuration files.
"""

import click
from pathlib import Path
from typing import Optional

from agent_actions.cli.validators.prompt_validator import PromptValidator
from agent_actions.cli.services.config_renderer import ConfigRenderer
from agent_actions.cli.services.project_paths_factory import ProjectPathsFactory
from agent_actions.workflow.agent_workflow import AgentWorkflow
from agent_actions.cli.exceptions import (
    ConfigurationError, 
    ValidationError,
    FileNotFoundError,
    AgentExecutionError
)

class RunCommand:
    """Implementation of the run command."""
    
    def __init__(self, agent: str, user_code: Optional[str], use_tools: bool):
        """
        Initialize the run command.
        
        Args:
            agent: Name of the agent configuration to run.
            user_code: Path to user-defined functions directory.
            use_tools: Whether to enable tool usage for agents.
        """
        self.agent = agent
        self.user_code = user_code
        self.use_tools = use_tools
        self.agent_name = Path(agent).stem
          
    def _find_config_file(self, config_dir: Path, filename: str) -> Path:
        """Find the configuration file."""
        full_path = config_dir / filename
        if not full_path.exists():
            raise FileNotFoundError(f"Configuration file not found at {full_path}")
        return full_path

    def execute(self, force: bool = False) -> None:
        """
        Execute the run command.
        
        Args:
            force: Force execution even if validation warnings occur
        
        Raises:
            Various exceptions depending on the stage that fails
        """
        click.echo(f"Starting agent run for: {self.agent}")
        
        try:
            click.echo("Setting up project paths...")
            paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.agent)   
            
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
                user_code_path=self.user_code,
                default_path=str(paths.default_config_path),
                use_tools=self.use_tools
            )
            
            click.echo("Starting workflow execution...")
            workflow.run()
            
            click.echo(f"Successfully completed agent run for: {self.agent}")
            
        except (ValidationError, FileNotFoundError, ConfigurationError, AgentExecutionError) as e:
            raise click.ClickException(str(e))
            
        except Exception as e:
            raise click.ClickException(f"Failed to run agent {self.agent}: {str(e)}")

@click.command()
@click.option('-a', '--agent', required=True,
              help="Agent configuration file name without path or extension")
@click.option('-u', '--user_code', help="Path to the user's code folder containing UDFs")
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
    command = RunCommand(agent, user_code, use_tools)
    command.execute(force)

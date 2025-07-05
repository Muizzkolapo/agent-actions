"""
Run command for the Agent Actions CLI.

This module provides the implementation of the 'run' command,
which executes agent workflows based on configuration files.
"""

import click
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from agent_actions.cli.validators.prompt_validator import PromptValidator
from agent_actions.cli.services.config_renderer import ConfigRenderer
from agent_actions.cli.services.project_paths_factory import ProjectPathsFactory
from agent_actions.cli.services.agent_runner_service import AgentRunnerService
from agent_actions.cli.exceptions import (
    ConfigurationError, 
    ValidationError,
    FileNotFoundError,
    AgentExecutionError
)
from agent_actions.services.batch_service import BatchService


class RunCommand:
    """Implementation of the run command."""
    
    def __init__(self, agent: str, user_code: Optional[str], batch_continue: bool = False, force_batch: bool = False):
        """
        Initialize the run command.
        
        Args:
            agent: Name of the agent configuration to run.
            user_code: Path to user-defined functions directory.
            batch_continue: Whether to continue workflow after processing completed batches.
            force_batch: Whether to force new batch submission even if existing jobs are in-flight.
        """
        self.agent = agent
        self.user_code = user_code
        self.batch_continue = batch_continue
        self.force_batch = force_batch
        self.agent_name = Path(agent).stem
          
    
    def _load_and_validate_config(self, full_path: Path, paths) -> str:
        """
        Load and validate the configuration data.
        
        Args:
            full_path: Path to the configuration file
            paths: Project paths container
            
        Returns:
            Parent pipeline name
        """
        click.echo("Rendering and loading configuration...")
        
        config_data = ConfigRenderer.render_and_load_config(
            self.agent_name, 
            full_path, 
            paths.template_dir, 
            paths.rendered_workflows_dir
        )
        
        agent_config = config_data[self.agent_name]
        parent_pipeline = AgentRunnerService.get_parent_pipeline(agent_config)
        return parent_pipeline

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
            instance = PromptValidator()
            instance.validate(paths.prompt_dir)    
            filename = f"{self.agent}.yml" if not self.agent.endswith(".yml") else self.agent
            full_path = AgentRunnerService.find_config_file(paths.agent_config_dir, filename)      
            parent_pipeline = self._load_and_validate_config(full_path, paths)
            click.echo(f"Starting workflow execution for pipeline: {parent_pipeline}")
            
            # Set batch force flag if requested
            if self.force_batch:
                BatchService.force_batch = True
            
            AgentRunnerService.run_agent_workflow(
                self.agent_name,
                full_path,
                paths.default_config_path,
                self.user_code,
                parent_pipeline,
                self.batch_continue
            )
            
            # Reset batch force flag after workflow
            BatchService.force_batch = False
            
            click.echo(f"Successfully completed agent run for: {self.agent}")
            
        except (ValidationError, FileNotFoundError, ConfigurationError, AgentExecutionError) as e:
            raise click.ClickException(str(e))
            
        except Exception as e:
            raise click.ClickException(f"Failed to run agent {self.agent}: {str(e)}")
    


@click.command()
@click.option('-a', '--agent', required=True,
              help="Agent configuration file name without path or extension")
@click.option('-u', '--user_code', help="Path to the user's code folder containing UDFs")
@click.option('--force', is_flag=True, help="Force execution even if validation warnings occur")
@click.option('--force_batch', is_flag=True, help="Force new batch submission even if existing batch jobs are in-flight")
@click.option('--batch_continue', is_flag=True, help="Continue workflow after checking batch status and processing completed batches")
def run(agent: str, user_code: Optional[str], force: bool = False, force_batch: bool = False, batch_continue: bool = False) -> None:
    """
    Run agents with a specified agent configuration.

    The run command executes agent workflows based on the specified configuration.
    It handles the entire lifecycle from loading configuration to executing 
    the workflow and processing results.

    Examples:
        agent-actions run -a my_agent
        agent-actions run -a my_agent -u ./user_code
    """
    command = RunCommand(agent, user_code, batch_continue, force_batch)
    command.execute(force)
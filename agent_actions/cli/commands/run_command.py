"""
Run command for the Agent Actions CLI.

This module provides the implementation of the 'run' command,
which executes agent workflows based on configuration files.
"""

import os
import yaml
import click
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple
from dataclasses import dataclass

from agent_actions.cli.validators.prompt_validator import PromptValidator
from agent_actions.cli.validators.directory_validator import DirectoryValidator
from agent_actions.cli.validators.config_validator import ConfigurationValidator
from agent_actions.cli.validators.schema_validator import SchemaValidator
from agent_actions.cli.services.config_renderer import ConfigRenderer
from agent_actions.cli.services.agent_config_parser import AgentConfigParser
from agent_actions.cli.services.project_paths_factory import ProjectPathsFactory
from agent_actions.cli.services.agent_runner_service import AgentRunnerService
from agent_actions.cli.exceptions import (
    ConfigurationError, 
    ValidationError,
    FileNotFoundError,
    AgentExecutionError
)


class RunCommand:
    """Implementation of the run command."""
    
    def __init__(self, agent: str, user_code: Optional[str]):
        """
        Initialize the run command.
        
        Args:
            agent: Name of the agent configuration to run.
            user_code: Path to user-defined functions directory.
        """
        self.agent = agent
        self.user_code = user_code
        self.agent_name = self._get_agent_name(agent)
        
    def _get_agent_name(self, agent: str) -> str:
        """
        Extract agent name from agent configuration parameter.
        
        Args:
            agent: Agent configuration parameter (with or without extension)
            
        Returns:
            Agent name without extension
        """
        return Path(agent).stem
    
    def _validate_prerequisites(self, paths) -> None:
        """
        Validate all prerequisites before running the agent.
        
        Args:
            paths: Project paths container
            
        Raises:
            ValidationError: If any validation fails
        """
        try:
            click.echo(f"Validating prompts for agent: {self.agent_name}")
            PromptValidator.validate_prompts(paths.prompt_dir)
            
            click.echo("Checking required directories...")
            required_dirs = [paths.agent_config_dir, paths.schema_dir, paths.io_dir]
            DirectoryValidator.check_required_directories(required_dirs)
            
        except Exception as e:
            raise ValidationError(f"Validation failed: {str(e)}") from e
    
    def _find_config_file(self, paths) -> Path:
        """
        Locate the configuration file.
        
        Args:
            paths: Project paths container
            
        Returns:
            Path to the configuration file
            
        Raises:
            FileNotFoundError: If the configuration file cannot be found
        """
        filename = f"{self.agent}.yml" if not self.agent.endswith(".yml") else self.agent
        click.echo(f"Locating configuration file: {filename}")
        
        full_path = AgentRunnerService.find_config_file(paths.agent_config_dir, filename)
        
        if full_path is None or not paths.default_config_path.exists():
            raise FileNotFoundError(f"Missing configuration file: {filename}")
        
        return full_path
    
    def _load_and_validate_config(self, full_path: Path, paths) -> Tuple[Dict[str, Any], str]:
        """
        Load and validate the configuration data.
        
        Args:
            full_path: Path to the configuration file
            paths: Project paths container
            
        Returns:
            Tuple of (agent_config, parent_pipeline)
        """
        click.echo("Rendering and loading configuration...")
        
        config_data = ConfigRenderer.render_and_load_config(
            self.agent_name, 
            full_path, 
            paths.template_dir, 
            paths.rendered_workflows_dir
        )
        
        agent_config = config_data[self.agent_name]
        parent_pipeline = AgentConfigParser.get_parent_pipeline(agent_config)
        return agent_config, parent_pipeline

    def execute(self) -> None:
        """
        Execute the run command.
        
        Raises:
            Various exceptions depending on the stage that fails
        """
        click.echo(f"Starting agent run for: {self.agent}")
        
        try:
            click.echo("Setting up project paths...")
            paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.agent)            
            self._validate_prerequisites(paths)            
            full_path = self._find_config_file(paths)
            agent_config, parent_pipeline = self._load_and_validate_config(full_path, paths)
            click.echo(f"Starting workflow execution for pipeline: {parent_pipeline}")
            
            AgentRunnerService.run_agent_workflow(
                self.agent_name,
                full_path,
                paths.default_config_path,
                self.user_code,
                parent_pipeline
            )
            
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
def run(agent: str, user_code: Optional[str], force: bool = False) -> None:
    """
    Run agents with a specified agent configuration.

    The run command executes agent workflows based on the specified configuration.
    It handles the entire lifecycle from loading configuration to executing 
    the workflow and processing results.

    Examples:
        agent-actions run -a my_agent
        agent-actions run -a my_agent -u ./user_code
    """
    command = RunCommand(agent, user_code)
    command.execute()
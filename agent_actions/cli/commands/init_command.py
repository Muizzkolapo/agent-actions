"""
Initialize command for the Agent Actions CLI.

This module provides the implementation of the 'init' command,
which handles creating new Agent Actions projects.
"""

import os
import click
import logging
from pathlib import Path
from typing import Optional, List

from agent_actions.core.init import ProjectInitializer
from agent_actions.cli.validators.project_validator import ProjectValidator
from agent_actions.cli.exceptions import (
    ValidationError,
    PermissionError,
    ConfigurationError
)

logger = logging.getLogger(__name__)


class InitCommand:
    """Implementation of the init command."""
    
    def __init__(self, project_name: str, output_dir: Optional[str] = None, 
                 template: str = 'default', force: bool = False):
        """
        Initialize the init command.
        
        Args:
            project_name: Name of the project to create.
            output_dir: Directory to create the project in (default: current directory).
            template: Template to use for project initialization.
            force: Whether to force initialization even if the directory exists.
        """
        self.project_name = project_name
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.template = template
        self.force = force
        self.project_dir = self.output_dir / self.project_name
    
    def _get_available_templates(self) -> List[str]:
        """
        Get a list of available templates.
        
        Returns:
            List of available template names.
        """
        # This is a placeholder - in a real implementation, we would scan
        # the templates directory to find available templates
        return ['default', 'minimal', 'full']
    
    def _create_project_directory(self) -> None:
        """
        Create the project directory.
        
        Raises:
            PermissionError: If there's a permission issue.
        """
        logger.debug(f"Creating project directory: {self.project_dir}")
        
        try:
            # Remove existing directory if force is True
            if self.project_dir.exists() and self.force:
                import shutil
                shutil.rmtree(self.project_dir)
            
            # Create the directory
            self.project_dir.mkdir(exist_ok=self.force)
            
        except PermissionError as e:
            raise PermissionError(f"Permission denied when creating project directory: {str(e)}")
        except Exception as e:
            raise ValidationError(f"Failed to create project directory: {str(e)}")
    
    def _initialize_project(self) -> None:
        """
        Initialize the project using ProjectInitializer.
        
        Raises:
            ConfigurationError: If project initialization fails.
        """
        logger.debug("Initializing project")
        
        try:
            initializer = ProjectInitializer(
                project_name=self.project_name,
                project_dir=str(self.project_dir),
                template=self.template
            )
            initializer.init_project()
            
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize project: {str(e)}")
    
    def execute(self) -> None:
        """
        Execute the init command.
        
        Raises:
            Various exceptions depending on what fails.
        """
        logger.info(f"Starting project initialization for: {self.project_name}")
        
        try:
            # Validate inputs using ProjectValidator
            ProjectValidator.validate_project_name(self.project_name)
            ProjectValidator.validate_project_directory(self.output_dir, self.project_dir, self.force)
            ProjectValidator.validate_template(self.template, self._get_available_templates())
            
            # Create project directory
            self._create_project_directory()
            
            # Initialize project
            self._initialize_project()
            
            # Success message
            logger.info(f"Successfully initialized project: {self.project_name}")
            click.echo(f"Successfully initialized project: {self.project_name}")
            click.echo(f"Project created at: {self.project_dir}")
            click.echo("\nNext steps:")
            click.echo(f"  cd {self.project_name}")
            click.echo("  agent-actions run -a sample_agent")
            
        except (ValidationError, PermissionError, ConfigurationError) as e:
            logger.error(f"{e.__class__.__name__}: {str(e)}")
            raise click.ClickException(str(e))
            
        except Exception as e:
            logger.error(f"Failed to initialize project {self.project_name}: {str(e)}", 
                         exc_info=True)
            raise click.ClickException(f"Failed to initialize project {self.project_name}: {str(e)}")


@click.command()
@click.argument('project_name')
@click.option('-o', '--output-dir', 
              help='Directory to create the project in (default: current directory)')
@click.option('-t', '--template', default='default',
              help='Template to use for project initialization')
@click.option('-f', '--force', is_flag=True, default=False,
              help='Force project creation even if directory exists')
def init(project_name: str, output_dir: Optional[str] = None, 
         template: str = 'default', force: bool = False) -> None:
    """
    Initialize a new Agent Actions project.

    This command creates a new project with the specified name.
    It sets up the directory structure, configuration files, and
    templates needed to start working with Agent Actions.

    Examples:
        agent-actions init my_project
        agent-actions init my_project --template minimal
        agent-actions init my_project --output-dir /path/to/dir
    """
    command = InitCommand(project_name, output_dir, template, force)
    command.execute()
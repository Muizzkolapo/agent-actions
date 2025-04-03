"""
Initialize command for the Agent Actions CLI.

This module provides the implementation of the 'init' command,
which handles creating new Agent Actions projects.
"""

import os
import click
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

from agent_actions.core.init import ProjectInitializer
from agent_actions.cli.exceptions import (
    ValidationError,
    PermissionError,
    ConfigurationError
)

logger = logging.getLogger(__name__)


class InitCommand:
    """Implementation of the init command."""
    
    # Project name validation pattern
    PROJECT_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')
    
    # Reserved names that cannot be used for projects
    RESERVED_NAMES = {
        'agent', 'actions', 'cli', 'core', 'docs', 'handlers', 
        'schema', 'templates', 'test', 'utils', 'workflow'
    }
    
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
    
    def _validate_project_name(self) -> None:
        """
        Validate the project name.
        
        Raises:
            ValidationError: If the project name is invalid.
        """
        logger.debug(f"Validating project name: {self.project_name}")
        
        # Check if the name is empty
        if not self.project_name:
            raise ValidationError("Project name cannot be empty")
        
        # Check if the name matches the pattern
        if not self.PROJECT_NAME_PATTERN.match(self.project_name):
            raise ValidationError(
                f"Invalid project name: {self.project_name}. "
                "Project names must start with a letter and contain only "
                "letters, numbers, underscores, and hyphens."
            )
        
        # Check if the name is reserved
        if self.project_name.lower() in self.RESERVED_NAMES:
            raise ValidationError(
                f"'{self.project_name}' is a reserved name and cannot be used as a project name"
            )
    
    def _validate_output_directory(self) -> None:
        """
        Validate the output directory.
        
        Raises:
            ValidationError: If the output directory validation fails.
            PermissionError: If there's a permission issue with the output directory.
        """
        logger.debug(f"Validating output directory: {self.output_dir}")
        
        # Check if the output directory exists
        if not self.output_dir.exists():
            raise ValidationError(f"Output directory does not exist: {self.output_dir}")
        
        # Check if the output directory is writable
        if not os.access(self.output_dir, os.W_OK):
            raise PermissionError(f"Output directory is not writable: {self.output_dir}")
        
        # Check if the project directory already exists
        if self.project_dir.exists() and not self.force:
            raise ValidationError(
                f"Project directory already exists: {self.project_dir}. "
                "Use --force to overwrite."
            )
    
    def _validate_template(self) -> None:
        """
        Validate the template.
        
        Raises:
            ValidationError: If the template validation fails.
        """
        logger.debug(f"Validating template: {self.template}")
        
        # Get available templates
        available_templates = self._get_available_templates()
        
        # Check if the template exists
        if self.template not in available_templates:
            raise ValidationError(
                f"Template '{self.template}' not found. "
                f"Available templates: {', '.join(available_templates)}"
            )
    
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
            # Validate inputs
            self._validate_project_name()
            self._validate_output_directory()
            self._validate_template()
            
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
            
        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            raise click.ClickException(f"Validation error: {str(e)}")
            
        except PermissionError as e:
            logger.error(f"Permission denied: {str(e)}")
            raise click.ClickException(f"Permission denied: {str(e)}")
            
        except ConfigurationError as e:
            logger.error(f"Configuration error: {str(e)}")
            raise click.ClickException(f"Configuration error: {str(e)}")
            
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
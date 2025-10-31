"""
Initialize command for the Agent Actions CLI.

This module provides the implementation of the 'init' command,
which handles creating new Agent Actions projects.
"""
import click
from pathlib import Path
from typing import Optional, List
from agent_actions.configuration.init import ProjectInitializer
from agent_actions.validation.project_validator import ProjectValidator
from agent_actions.shared.exceptions import ValidationError, FileSystemError, ConfigurationError
from agent_actions.validation.init_validator import InitCommandArgs
from agent_actions.cli.cli_decorators import handles_user_errors
from pydantic import ValidationError as PydanticValidationError

class InitCommand:
    """Implementation of the init command."""

    def __init__(self, args: InitCommandArgs):
        """
        Initialize the init command.
        
        Args:
            args: Pydantic model containing the command arguments.
        """
        self.args = args
        self.output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
        self.project_dir = self.output_dir / self.args.project_name

    def _get_available_templates(self) -> List[str]:
        """
        Get a list of available templates.
        
        Returns:
            List of available template names.
        """
        return ['default', 'minimal', 'full']

    def _create_project_directory(self) -> None:
        """
        Create the project directory.
        
        Raises:
            FileSystemError: If there's a permission issue.
        """
        try:
            if self.project_dir.exists() and self.args.force:
                import shutil
                shutil.rmtree(self.project_dir)
            self.project_dir.mkdir(exist_ok=self.args.force)
        except FileSystemError as e:
            raise FileSystemError('Permission denied when creating project directory', context={'project_dir': str(self.project_dir), 'project_name': self.args.project_name, 'operation': '_create_project_directory'}, cause=e) from e
        except Exception as e:
            raise ValidationError('Failed to create project directory', context={'project_dir': str(self.project_dir), 'project_name': self.args.project_name, 'operation': '_create_project_directory'}, cause=e) from e

    def _initialize_project(self) -> None:
        """
        Initialize the project using ProjectInitializer.
        
        Raises:
            ConfigurationError: If project initialization fails.
        """
        try:
            initializer = ProjectInitializer(project_name=self.args.project_name, project_dir=str(self.project_dir), template=self.args.template)
            initializer.init_project()
        except Exception as e:
            raise ConfigurationError('Failed to initialize project', context={'project_name': self.args.project_name, 'project_dir': str(self.project_dir), 'template': self.args.template, 'operation': '_initialize_project'}, cause=e) from e

    def execute(self) -> None:
        """
        Execute the init command.

        Raises:
            Various exceptions depending on what fails.
        """
        ProjectValidator.validate_project_name(self.args.project_name)
        ProjectValidator.validate_project_directory(self.output_dir, self.project_dir, self.args.force)
        ProjectValidator.validate_template(self.args.template, self._get_available_templates())
        self._create_project_directory()
        self._initialize_project()
        click.echo(f'Successfully initialized project: {self.args.project_name}')
        click.echo(f'Project created at: {self.project_dir}')
        click.echo('\nNext steps:')
        click.echo(f'  cd {self.args.project_name}')
        click.echo('  agent-actions run -a sample_agent')

@click.command()
@click.argument('project_name')
@click.option('-o', '--output-dir', help='Directory to create the project in (default: current directory)')
@click.option('-t', '--template', default='default', help='Template to use for project initialization')
@click.option('-f', '--force', is_flag=True, default=False, help='Force project creation even if directory exists')
@handles_user_errors('init')
def init(project_name: str, output_dir: Optional[str]=None, template: str='default', force: bool=False) -> None:
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
    args = InitCommandArgs(project_name=project_name, output_dir=output_dir, template=template, force=force)
    command = InitCommand(args)
    command.execute()
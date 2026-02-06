"""
Initialize command for the Agent Actions CLI.

This module provides the implementation of the 'init' command,
which handles creating new Agent Actions projects.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import click

from agent_actions.cli.cli_decorators import handles_user_errors
from agent_actions.config.init import ProjectInitializer
from agent_actions.errors import (
    ValidationError,
    FileSystemError,
    ConfigurationError,
)  # New modular pattern!
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    ProjectInitializationStartEvent,
    ProjectValidationEvent,
    ProjectDirectoryCreatedEvent,
    ProjectInitializedEvent,
)
from agent_actions.validation.init_validator import InitCommandArgs
from agent_actions.validation.project_validator import ProjectValidator


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

        # Security: Validate output_dir doesn't escape via path traversal
        self._validate_output_dir()

        self.project_dir = self.output_dir / self.args.project_name

    def _validate_output_dir(self) -> None:
        """
        Validate output directory is safe for project creation.

        Checks:
        1. No path traversal patterns (..)
        2. Resolved path is within current working directory or its children
        3. Path doesn't escape to system directories

        Raises:
            ValidationError: If path validation fails.
        """
        cwd = Path.cwd().resolve()
        resolved = self.output_dir.resolve()

        # If output_dir was explicitly provided, validate it
        if self.args.output_dir:
            path_str = str(Path(self.args.output_dir))

            # Check for explicit path traversal patterns
            if ".." in path_str:
                raise ValidationError(
                    "Path traversal not allowed in output directory",
                    context={
                        "output_dir": path_str,
                        "resolved": str(resolved),
                        "operation": "_validate_output_dir",
                    },
                )

            # Ensure resolved path is within cwd or is an absolute path the user explicitly chose
            # For relative paths, they must resolve within cwd
            if not Path(self.args.output_dir).is_absolute():
                try:
                    resolved.relative_to(cwd)
                except ValueError as exc:
                    raise ValidationError(
                        "Output directory must be within current working directory",
                        context={
                            "output_dir": path_str,
                            "resolved": str(resolved),
                            "cwd": str(cwd),
                            "operation": "_validate_output_dir",
                        },
                    ) from exc

        # Additional safety: prevent writing to sensitive system directories
        sensitive_prefixes = ("/etc", "/usr", "/bin", "/sbin", "/var", "/root")
        resolved_str = str(resolved)
        for prefix in sensitive_prefixes:
            if resolved_str.startswith(prefix):
                raise ValidationError(
                    "Cannot create project in system directory",
                    context={
                        "output_dir": str(self.output_dir),
                        "resolved": resolved_str,
                        "blocked_prefix": prefix,
                        "operation": "_validate_output_dir",
                    },
                )

    def _get_available_templates(self) -> List[str]:
        """
        Get a list of available templates.

        Returns:
            List of available template names.
        """
        return ["default", "minimal", "full"]

    def _create_project_directory(self) -> None:
        """
        Create the project directory.

        Raises:
            FileSystemError: If there's a permission issue.
        """
        try:
            if self.project_dir.exists() and self.args.force:
                shutil.rmtree(self.project_dir)
            self.project_dir.mkdir(exist_ok=self.args.force)
        except FileSystemError as e:
            raise FileSystemError(
                "Permission denied when creating project directory",
                context={
                    "project_dir": str(self.project_dir),
                    "project_name": self.args.project_name,
                    "operation": "_create_project_directory",
                },
                cause=e,
            ) from e
        except Exception as e:
            raise ValidationError(
                "Failed to create project directory",
                context={
                    "project_dir": str(self.project_dir),
                    "project_name": self.args.project_name,
                    "operation": "_create_project_directory",
                },
                cause=e,
            ) from e

    def _initialize_project(self) -> None:
        """
        Initialize the project using ProjectInitializer.

        Raises:
            ConfigurationError: If project initialization fails.
        """
        try:
            # ProjectInitializer takes project_name and base_path (parent dir)
            initializer = ProjectInitializer(
                project_name=self.args.project_name, base_path=self.output_dir
            )
            initializer.init_project()
        except Exception as e:
            raise ConfigurationError(
                "Failed to initialize project",
                context={
                    "project_name": self.args.project_name,
                    "project_dir": str(self.project_dir),
                    "template": self.args.template,
                    "operation": "_initialize_project",
                },
                cause=e,
            ) from e

    def execute(self) -> None:
        """
        Execute the init command.

        Raises:
            Various exceptions depending on what fails.
        """
        # Fire project initialization start event
        start_time = datetime.now()
        fire_event(ProjectInitializationStartEvent(project_path=str(self.project_dir)))

        # Use ProjectValidator.validate() with data dict
        validator = ProjectValidator()
        validation_data = {
            "project_name": self.args.project_name,
            "output_dir": self.output_dir,
            "project_dir": self.project_dir,
            "template": self.args.template,
            "available_templates": self._get_available_templates(),
            "force": self.args.force,
        }
        fire_event(
            ProjectValidationEvent(validation_target="project_structure", result="validating")
        )
        if not validator.validate(validation_data):
            fire_event(
                ProjectValidationEvent(validation_target="project_structure", result="failed")
            )
            errors = validator.get_errors()
            raise ValidationError("Project validation failed", context={"errors": errors})
        fire_event(ProjectValidationEvent(validation_target="project_structure", result="passed"))

        self._create_project_directory()
        fire_event(ProjectDirectoryCreatedEvent(directory_path=str(self.project_dir)))

        self._initialize_project()

        # Fire project initialization complete event
        elapsed_time = (datetime.now() - start_time).total_seconds()
        fire_event(
            ProjectInitializedEvent(project_path=str(self.project_dir), elapsed_time=elapsed_time)
        )

        click.echo(f"Successfully initialized project: {self.args.project_name}")
        click.echo(f"Project created at: {self.project_dir}")
        click.echo("\nNext steps:")
        click.echo(f"  cd {self.args.project_name}")
        click.echo("  agent-actions run -a sample_agent")


@click.command()
@click.argument("project_name")
@click.option(
    "-o", "--output-dir", help="Directory to create the project in (default: current directory)"
)
@click.option(
    "-t", "--template", default="default", help="Template to use for project initialization"
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Force project creation even if directory exists",
)
@handles_user_errors("init")
def init(
    project_name: str,
    output_dir: Optional[str] = None,
    template: str = "default",
    force: bool = False,
) -> None:
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
    args = InitCommandArgs(
        project_name=project_name, output_dir=output_dir, template=template, force=force
    )
    command = InitCommand(args)
    command.execute()

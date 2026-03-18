"""Initialize command for the Agent Actions CLI."""

import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors
from agent_actions.config.init import ProjectInitializer
from agent_actions.errors import (
    ConfigurationError,
    FileSystemError,
    ValidationError,
)
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    ProjectDirectoryCreatedEvent,
    ProjectInitializationStartEvent,
    ProjectInitializedEvent,
    ProjectValidationEvent,
)
from agent_actions.validation.init_validator import InitCommandArgs
from agent_actions.validation.project_validator import ProjectValidator

logger = logging.getLogger(__name__)


class InitCommand:
    """Handles project initialization including validation and directory creation."""

    def __init__(self, args: InitCommandArgs):
        self.args = args
        self.output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()

        self._validate_output_dir()

        self.project_dir = self.output_dir / self.args.project_name

    def _validate_output_dir(self) -> None:
        cwd = Path.cwd().resolve()
        resolved = self.output_dir.resolve()

        if self.args.output_dir:
            path_str = str(Path(self.args.output_dir))

            if any(part == ".." for part in Path(self.args.output_dir).parts):
                raise ValidationError(
                    "Path traversal not allowed in output directory",
                    context={
                        "output_dir": path_str,
                        "resolved": str(resolved),
                        "operation": "_validate_output_dir",
                    },
                )

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

        sensitive_prefixes = ("/etc/", "/usr/", "/bin/", "/sbin/", "/var/", "/root/")
        resolved_str = str(resolved)
        for prefix in sensitive_prefixes:
            if resolved_str.startswith(prefix) or resolved_str.rstrip("/") + "/" == prefix:
                raise ValidationError(
                    "Cannot create project in system directory",
                    context={
                        "output_dir": str(self.output_dir),
                        "resolved": resolved_str,
                        "blocked_prefix": prefix,
                        "operation": "_validate_output_dir",
                    },
                )

    def _get_available_templates(self) -> list[str]:
        return ["default", "minimal", "full"]

    def _create_project_directory(self) -> None:
        try:
            backup_dir = None
            if self.project_dir.exists() and self.args.force:
                backup_dir = Path(
                    tempfile.mkdtemp(
                        prefix=f".{self.project_dir.name}_bak_",
                        dir=str(self.project_dir.parent),
                    )
                )
                shutil.rmtree(backup_dir)
                self.project_dir.rename(backup_dir)
            self.project_dir.mkdir(exist_ok=self.args.force)
            if backup_dir and backup_dir.exists():
                try:
                    shutil.rmtree(backup_dir)
                except OSError as cleanup_err:
                    logger.warning("Failed to clean up backup %s: %s", backup_dir, cleanup_err)
        except OSError as e:
            if backup_dir and backup_dir.exists() and not self.project_dir.exists():
                backup_dir.rename(self.project_dir)
            raise FileSystemError(
                "Failed to create project directory",
                context={
                    "project_dir": str(self.project_dir),
                    "project_name": self.args.project_name,
                    "operation": "_create_project_directory",
                    "os_error": str(e),
                },
                cause=e,
            ) from e

    def _initialize_project(self) -> None:
        try:
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
        start_time = datetime.now()
        fire_event(ProjectInitializationStartEvent(project_path=str(self.project_dir)))

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

        elapsed_time = (datetime.now() - start_time).total_seconds()
        fire_event(
            ProjectInitializedEvent(project_path=str(self.project_dir), elapsed_time=elapsed_time)
        )

        click.echo(f"Successfully initialized project: {self.args.project_name}")
        click.echo(f"Project created at: {self.project_dir}")
        click.echo("\nNext steps:")
        click.echo(f"  cd {self.args.project_name}")
        click.echo("  agac run -a sample_agent")


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
    output_dir: str | None = None,
    template: str = "default",
    force: bool = False,
) -> None:
    """
    Initialize a new Agent Actions project.

    This command creates a new project with the specified name.
    It sets up the directory structure, configuration files, and
    templates needed to start working with Agent Actions.

    Examples:
        agac init my_project
        agac init my_project --template minimal
        agac init my_project --output-dir /path/to/dir
    """
    args = InitCommandArgs(
        project_name=project_name,
        output_dir=Path(output_dir) if output_dir else None,
        template=template,
        force=force,
    )
    command = InitCommand(args)
    command.execute()

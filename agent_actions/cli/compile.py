"""Render command for the Agent Actions CLI."""

import logging
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.path_config import resolve_project_root
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.validation.render_validator import RenderCommandArgs

logger = logging.getLogger(__name__)


class RenderCommand:
    def __init__(self, args: RenderCommandArgs, project_root: Path | None = None):
        self.args = args
        self._project_root = project_root
        root = resolve_project_root(project_root)
        if args.template_dir:
            td = Path(args.template_dir)
            # Resolve relative paths against project_root, not CWD
            self.template_dir = td if td.is_absolute() else root / td
        else:
            self.template_dir = root / "templates"

    def _render_template(self, agent_config_file: Path) -> str:
        try:
            logger.info(
                "Rendering template with configuration...",
                extra={
                    "agent_name": self.args.agent_name,
                    "config_file": str(agent_config_file),
                    "template_dir": str(self.template_dir),
                },
            )
            rendered_template = render_pipeline_with_templates(
                str(agent_config_file), str(self.template_dir), project_root=self._project_root
            )
            logger.info(
                "Template rendering completed successfully",
                extra={"agent_name": self.args.agent_name},
            )
            return rendered_template
        except Exception as e:
            logger.error(
                "Template rendering failed: %s", str(e), extra={"agent_name": self.args.agent_name}
            )
            logger.debug("Template rendering exception details", exc_info=True)
            raise TemplateRenderingError(
                "Failed to render template",
                context={
                    "agent_name": self.args.agent_name,
                    "config_file": str(agent_config_file),
                    "template_dir": str(self.template_dir),
                    "operation": "_render_template",
                },
                cause=e,
            ) from e

    def execute(self, create_dirs: bool = False) -> None:
        if create_dirs and not self.template_dir.exists():
            self.template_dir.mkdir(parents=True)
        logger.info("Starting template rendering for agent: %s", self.args.agent_name)
        paths = ProjectPathsFactory.create_project_paths(
            self.args.agent_name, self.args.agent_name, project_root=self._project_root
        )
        agent_config_file = paths.agent_config_dir / f"{self.args.agent_name}.yml"
        rendered_template = self._render_template(agent_config_file)
        click.echo(rendered_template)
        logger.info(
            "Rendered agent template output to console", extra={"agent": self.args.agent_name}
        )


def _execute_render(
    agent_name: str,
    template_dir: str | None = None,
    project_root: Path | None = None,
    create_dirs: bool = False,
) -> None:
    """Shared implementation for render/compile commands."""
    args = RenderCommandArgs(agent_name=agent_name, template_dir=template_dir)
    command = RenderCommand(args, project_root=project_root)
    command.execute(create_dirs=create_dirs)


@click.command()
@click.option(
    "-a", "--agent", "agent_name", required=True, help="Name of the agent to render template for"
)
@click.option("-t", "--template-dir", help="Directory containing templates (default: ./templates)")
@click.option(
    "--create-dirs",
    is_flag=True,
    default=False,
    help="Create template directory if it does not exist",
)
@handles_user_errors("render")
@requires_project
def render(
    agent_name: str,
    template_dir: str | None = None,
    create_dirs: bool = False,
    project_root: Path | None = None,
) -> None:
    """
    Compile and render workflow configuration.

    This is the single compilation step for workflows.
    After rendering, the YAML is fully self-contained with:

    \b
    - Jinja2 templates resolved
    - Prompt references ($prompt_name) loaded
    - Named schemas inlined from schema/ directory
    - Inline schemas expanded to unified format
    - Versioned actions expanded

    Useful for debugging template issues, verifying schema inlining,
    and troubleshooting YAML parsing errors.

    Examples:
        # Render workflow config to console
        agac render -a my_workflow

        # Render with custom templates directory
        agac render -a my_workflow -t custom_templates
    """
    _execute_render(agent_name, template_dir, project_root=project_root, create_dirs=create_dirs)


@click.command()
@click.option("-a", "--agent", "agent_name", required=True, help="Name of the workflow to compile")
@click.option("-t", "--template-dir", help="Directory containing templates (default: ./templates)")
@click.option(
    "--create-dirs",
    is_flag=True,
    default=False,
    help="Create template directory if it does not exist",
)
@handles_user_errors("compile")
@requires_project
def compile(
    agent_name: str,
    template_dir: str | None = None,
    create_dirs: bool = False,
    project_root: Path | None = None,
) -> None:
    """
    Alias for 'render' - compile workflow configuration.

    See 'agac render --help' for full documentation.

    Examples:
        agac compile -a my_workflow
    """
    _execute_render(agent_name, template_dir, project_root=project_root, create_dirs=create_dirs)

"""Render command for the Agent Actions CLI."""

import logging
import os
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.validation.render_validator import RenderCommandArgs

logger = logging.getLogger(__name__)


class RenderCommand:
    def __init__(self, args: RenderCommandArgs):
        self.args = args
        self.template_dir = (
            Path(args.template_dir) if args.template_dir else Path(os.getcwd()) / "templates"
        )

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
                str(agent_config_file), str(self.template_dir)
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

    def execute(self) -> None:
        logger.info("Starting template rendering for agent: %s", self.args.agent_name)
        paths = ProjectPathsFactory.create_project_paths(self.args.agent_name, self.args.agent_name)
        agent_config_file = paths.agent_config_dir / f"{self.args.agent_name}.yml"
        rendered_template = self._render_template(agent_config_file)
        click.echo(rendered_template)
        logger.info(
            "Rendered agent template output to console", extra={"agent": self.args.agent_name}
        )


def _execute_render(agent_name: str, template_dir: str | None = None) -> None:
    """Shared implementation for render/compile commands."""
    args = RenderCommandArgs(agent_name=agent_name, template_dir=template_dir)
    command = RenderCommand(args)
    command.execute()


@click.command()
@click.option(
    "-a", "--agent", "agent_name", required=True, help="Name of the agent to render template for"
)
@click.option("-t", "--template-dir", help="Directory containing templates (default: ./templates)")
@handles_user_errors("render")
@requires_project
def render(agent_name: str, template_dir: str | None = None) -> None:
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
    _execute_render(agent_name, template_dir)


@click.command()
@click.option("-a", "--agent", "agent_name", required=True, help="Name of the workflow to compile")
@click.option("-t", "--template-dir", help="Directory containing templates (default: ./templates)")
@handles_user_errors("compile")
@requires_project
def compile(agent_name: str, template_dir: str | None = None) -> None:
    """
    Alias for 'render' - compile workflow configuration.

    See 'agac render --help' for full documentation.

    Examples:
        agac compile -a my_workflow
    """
    _execute_render(agent_name, template_dir)

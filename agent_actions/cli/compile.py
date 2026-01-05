"""
Render command for the Agent Actions CLI.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import click

from agent_actions.cli.cli_decorators import requires_project, handles_user_errors
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from agent_actions.errors import TemplateRenderingError  # New modular pattern!
from agent_actions.prompt_generation.render_workflow import render_pipeline_with_templates
from agent_actions.validation.render_validator import RenderCommandArgs

logger = logging.getLogger(__name__)


class RenderCommand:
    """Implementation of the render command."""

    def __init__(self, args: RenderCommandArgs):
        """Initialize the render command."""
        self.args = args
        self.template_dir = (
            Path(args.template_dir) if args.template_dir else Path(os.getcwd()) / "templates"
        )

    def _render_template(self, agent_config_file: Path) -> str:
        """Render the template with the agent configuration."""
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
            # Log error without traceback (will be handled by error formatter)
            logger.error(
                "Template rendering failed: %s", str(e), extra={"agent_name": self.args.agent_name}
            )
            # Log full traceback only at debug level
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
        """Execute the render command."""
        logger.info("Starting template rendering for agent: %s", self.args.agent_name)
        paths = ProjectPathsFactory.create_project_paths(self.args.agent_name, self.args.agent_name)
        agent_config_file = paths.agent_config_dir / f"{self.args.agent_name}.yml"
        rendered_template = self._render_template(agent_config_file)
        click.echo(rendered_template)
        logger.info(
            "Rendered agent template output to console", extra={"agent": self.args.agent_name}
        )


@click.command()
@click.option(
    "-a", "--agent", "agent_name", required=True, help="Name of the agent to render template for"
)
@click.option("-t", "--template-dir", help="Directory containing templates (default: ./templates)")
@handles_user_errors("render")
@requires_project
def render(agent_name: str, template_dir: Optional[str] = None) -> None:
    """
    Render Jinja2 templates in agent configuration files.

    This command processes agent configuration files and renders them using Jinja2
    templates in the template directory. Useful for debugging template issues,
    verifying macro expansion, and troubleshooting YAML parsing errors.

    The rendered output is always displayed to the console.

    Examples:
        # Render agent config to console
        agent-actions render -a my_agent

        # Render with custom templates directory
        agent-actions render -a my_agent -t custom_templates
    """
    args = RenderCommandArgs(agent_name=agent_name, template_dir=template_dir)
    command = RenderCommand(args)
    command.execute()

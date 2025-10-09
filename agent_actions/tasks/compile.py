"""
Render command for the Agent Actions CLI.
"""

import os
import click
import logging
from pathlib import Path
from typing import Optional

from agent_actions.core.graph.render_workflow import render_pipeline_with_templates
from agent_actions.core.exceptions import (
    ValidationError,
    FileLoadError,
    TemplateRenderingError
)
from agent_actions.agents.validators.render_validator import RenderCommandArgs
from agent_actions.core.cli_decorators import requires_project
from pydantic import ValidationError as PydanticValidationError

logger = logging.getLogger(__name__)


class RenderCommand:
    """Implementation of the render command."""

    def __init__(self, args: RenderCommandArgs):
        """Initialize the render command."""
        self.args = args
        self.template_dir = Path(args.template_dir) if args.template_dir else Path(os.getcwd()) / "templates"
    
    def _render_template(self, agent_config_file: Path) -> str:
        """Render the template with the agent configuration."""
        try:
            logger.info("Rendering template with configuration...", extra={
                'agent_name': self.args.agent_name,
                'config_file': str(agent_config_file),
                'template_dir': str(self.template_dir)
            })

            rendered_template = render_pipeline_with_templates(
                str(agent_config_file),
                str(self.template_dir)
            )

            logger.info("Template rendering completed successfully", extra={
                'agent_name': self.args.agent_name
            })

            return rendered_template

        except Exception as e:
            logger.error(f"Template rendering failed: {str(e)}",
                        extra={'agent_name': self.args.agent_name}, exc_info=True)
            raise TemplateRenderingError(
                "Failed to render template",
                context={'agent_name': self.args.agent_name, 'config_file': str(agent_config_file), 'template_dir': str(self.template_dir), 'operation': '_render_template'},
                cause=e
            ) from e
    
    def execute(self) -> None:
        """Execute the render command."""
        try:
            logger.info(f"Starting template rendering for agent: {self.args.agent_name}")

            from agent_actions.tasks.services.project_paths_factory import ProjectPathsFactory
            paths = ProjectPathsFactory.create_project_paths(self.args.agent_name, self.args.agent_name)
            agent_config_file = paths.agent_config_dir / f"{self.args.agent_name}.yml"

            # Render the template
            rendered_template = self._render_template(agent_config_file)

            # Output to console
            click.echo(rendered_template)
            logger.info(f"Rendered agent template output to console", extra={'agent': self.args.agent_name})

        except (FileLoadError, ValidationError, TemplateRenderingError) as e:
            logger.error(f"{e.__class__.__name__}: {str(e)}")
            from agent_actions.core.user_errors import format_user_error
            context = {
                'command': 'render',
                'agent': self.args.agent_name
            }
            error_message = format_user_error(e, context)
            raise click.ClickException(error_message)

        except Exception as e:
            logger.error(f"Failed to render template for {self.args.agent_name}: {str(e)}", exc_info=True)
            raise click.ClickException(f"Failed to render template for {self.args.agent_name}: {str(e)}")


@click.command()
@click.option('-a', '--agent', 'agent_name', required=True,
              help="Name of the agent to render template for")
@click.option('-t', '--template-dir',
              help="Directory containing templates (default: ./templates)")
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
    try:
        args = RenderCommandArgs(
            agent_name=agent_name,
            template_dir=template_dir
        )
        command = RenderCommand(args)
        command.execute()
    except PydanticValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'render'})
        raise click.ClickException(error_message)

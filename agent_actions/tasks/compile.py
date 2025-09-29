"""
Render command for the Agent Actions CLI.
"""

import os
import click
import logging
from pathlib import Path
from typing import Optional

from agent_actions.core.graph.render_workflow import render_pipeline_with_templates
from agent_actions.cli.exceptions import (
    ValidationError,
    FileNotFoundError,
    TemplateRenderingError
)
from agent_actions.agents.validators.render_validator import RenderCommandArgs
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
            
            output_path = self.args.output_file if self.args.output_file else None
            rendered_template = render_pipeline_with_templates(
                str(agent_config_file), 
                str(self.template_dir),
                str(output_path)
            )
            
            logger.info("Template rendering completed successfully", extra={
                'agent_name': self.args.agent_name
            })
            
            return rendered_template
            
        except Exception as e:
            logger.error(f"Template rendering failed: {str(e)}", 
                        extra={'agent_name': self.args.agent_name}, exc_info=True)
            raise TemplateRenderingError(f"Failed to render template: {str(e)}") from e
    
    def execute(self) -> None:
        """Execute the render command."""
        logger.info(f"Starting template rendering for agent: {self.args.agent_name}")
        
        try:
            from agent_actions.tasks.services.project_paths_factory import ProjectPathsFactory
            paths = ProjectPathsFactory.create_project_paths(self.args.agent_name, self.args.agent_name)
            agent_config_file = paths.agent_config_dir / f"{self.args.agent_name}.yml"
            
            # Render the template
            rendered_template = self._render_template(agent_config_file)
            
            # Output the result
            if not self.args.output_file:
                click.echo(rendered_template)
                logger.info("Rendered template output to console", extra={
                    'agent_name': self.args.agent_name
                })
            else:
                logger.info(f"Rendered template saved to {self.args.output_file}", extra={
                    'agent_name': self.args.agent_name
                })
                click.echo(f"Template rendered successfully and saved to {self.args.output_file}")
            
        except (FileNotFoundError, ValidationError, TemplateRenderingError) as e:
            logger.error(f"{e.__class__.__name__}: {str(e)}")
            from agent_actions.core.user_errors import format_user_error
            error_message = format_user_error(e, {'command': 'render', 'agent': self.args.agent_name})
            raise click.ClickException(error_message)
            
        except Exception as e:
            logger.error(f"Failed to render template for agent {self.args.agent_name}: {str(e)}", 
                        exc_info=True)
            raise click.ClickException(
                f"Failed to render template for agent {self.args.agent_name}: {str(e)}"
            )


@click.command()
@click.option('-a', '--agent', 'agent_name', required=True,
              help="Name of the agent to render template for")
@click.option('-o', '--output', 'output_file',
              help="Path to save the rendered template (default: output to console)")
@click.option('-t', '--template-dir',
              help="Directory containing templates (default: ./templates)")
def render(agent_name: str, output_file: Optional[str] = None, 
          template_dir: Optional[str] = None) -> None:
    """
    Render a Jinja template for the specified agent.

    This command processes the agent configuration file and renders
    it using the Jinja templates in the template directory. The output
    can be saved to a file or displayed in the console.

    Examples:
        agent-actions render -a my_agent
        agent-actions render --agent my_agent -o rendered_output.yml
        agent-actions render -a my_agent -t custom_templates
    """
    try:
        args = RenderCommandArgs(agent_name=agent_name, output_file=output_file, template_dir=template_dir)
        command = RenderCommand(args)
        command.execute()
    except PydanticValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'render'})
        raise click.ClickException(error_message)

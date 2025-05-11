"""
Render command for the Agent Actions CLI.
"""

import os
import click
import logging
from pathlib import Path
from typing import Optional

from agent_actions.workflow.render_workflow import render_pipeline_with_templates
from agent_actions.cli.validators.render_validator import RenderValidator
from agent_actions.cli.exceptions import (
    ValidationError,
    FileNotFoundError,
    TemplateRenderingError
)

logger = logging.getLogger(__name__)


class RenderCommand:
    """Implementation of the render command."""
    
    def __init__(self, agent_name: str, output_file: Optional[str] = None, 
                 template_dir: Optional[str] = None):
        """Initialize the render command."""
        self.agent_name = agent_name
        self.output_file = output_file
        self.template_dir = Path(template_dir) if template_dir else Path(os.getcwd()) / "templates"
    
    def _render_template(self, agent_config_file: Path) -> str:
        """Render the template with the agent configuration."""
        try:
            logger.info("Rendering template with configuration...", extra={
                'agent_name': self.agent_name,
                'config_file': str(agent_config_file),
                'template_dir': str(self.template_dir)
            })
            
            output_path = self.output_file if self.output_file else None
            rendered_template = render_pipeline_with_templates(
                str(agent_config_file), 
                str(self.template_dir),
                output_path
            )
            
            logger.info("Template rendering completed successfully", extra={
                'agent_name': self.agent_name
            })
            
            return rendered_template
            
        except Exception as e:
            logger.error(f"Template rendering failed: {str(e)}", 
                        extra={'agent_name': self.agent_name}, exc_info=True)
            raise TemplateRenderingError(f"Failed to render template: {str(e)}") from e
    
    def execute(self) -> None:
        """Execute the render command."""
        logger.info(f"Starting template rendering for agent: {self.agent_name}")
        
        try:
            # Validate inputs using RenderValidator
            RenderValidator.validate_template_directory(self.template_dir)
            if self.output_file:
                RenderValidator.validate_output_file(self.output_file)
            
            # Get and validate agent paths
            _, agent_config_file = RenderValidator.validate_agent_paths(self.agent_name)
            
            # Render the template
            rendered_template = self._render_template(agent_config_file)
            
            # Output the result
            if not self.output_file:
                click.echo(rendered_template)
                logger.info("Rendered template output to console", extra={
                    'agent_name': self.agent_name
                })
            else:
                logger.info(f"Rendered template saved to {self.output_file}", extra={
                    'agent_name': self.agent_name
                })
                click.echo(f"Template rendered successfully and saved to {self.output_file}")
            
        except (FileNotFoundError, ValidationError, TemplateRenderingError) as e:
            logger.error(f"{e.__class__.__name__}: {str(e)}")
            raise click.ClickException(str(e))
            
        except Exception as e:
            logger.error(f"Failed to render template for agent {self.agent_name}: {str(e)}", 
                        exc_info=True)
            raise click.ClickException(
                f"Failed to render template for agent {self.agent_name}: {str(e)}"
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
    command = RenderCommand(agent_name, output_file, template_dir)
    command.execute()
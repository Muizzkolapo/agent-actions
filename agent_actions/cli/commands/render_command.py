"""
Render command for the Agent Actions CLI.

This module provides the implementation of the 'render' command,
which handles rendering templates for agents.
"""

import os
import click
import logging
from pathlib import Path
from typing import Optional, Tuple

from agent_actions.handlers.file_handler import FileHandler
from agent_actions.workflow.render_workflow import render_pipeline_with_templates
from agent_actions.cli.exceptions import (
    AgentActionsError,
    ValidationError,
    FileNotFoundError,
    TemplateRenderingError
)

logger = logging.getLogger(__name__)


class RenderCommand:
    """Implementation of the render command."""
    
    def __init__(self, agent_name: str, output_file: Optional[str] = None, 
                 template_dir: Optional[str] = None):
        """
        Initialize the render command.
        
        Args:
            agent_name: Name of the agent template to render.
            output_file: Optional path to output file. If None, prints to stdout.
            template_dir: Optional path to template directory. If None, uses default.
        """
        self.agent_name = agent_name
        self.output_file = output_file
        self.template_dir = Path(template_dir) if template_dir else Path(os.getcwd()) / "templates"
    
    def _get_agent_paths(self) -> Tuple[Path, Path]:
        """
        Get the agent configuration directory and file path.
        
        Returns:
            Tuple of (agent_config_dir, agent_config_file)
            
        Raises:
            FileNotFoundError: If the agent configuration file or directory is not found.
        """
        try:
            # Get agent directories
            agent_config_dir_str, _, _ = FileHandler.get_agent_paths(self.agent_name)
            agent_config_dir = Path(agent_config_dir_str)
            
            if not agent_config_dir.exists():
                raise FileNotFoundError(f"Agent configuration directory not found: {agent_config_dir}")
            
            # Find the configuration file
            agent_config_file_str = FileHandler.find_config_file(
                str(agent_config_dir), 
                f"{self.agent_name}.yml"
            )
            
            if not agent_config_file_str:
                raise FileNotFoundError(f"Missing configuration file: {self.agent_name}.yml")
            
            agent_config_file = Path(agent_config_file_str)
            return agent_config_dir, agent_config_file
            
        except Exception as e:
            if isinstance(e, FileNotFoundError):
                raise
            raise FileNotFoundError(f"Failed to locate agent configuration: {str(e)}") from e
    
    def _validate_template_directory(self) -> None:
        """
        Validate that the template directory exists and is readable.
        
        Raises:
            ValidationError: If the template directory is invalid.
        """
        if not self.template_dir.exists():
            raise ValidationError(f"Template directory does not exist: {self.template_dir}")
        
        if not self.template_dir.is_dir():
            raise ValidationError(f"Template path is not a directory: {self.template_dir}")
        
        if not os.access(self.template_dir, os.R_OK):
            raise ValidationError(f"Template directory is not readable: {self.template_dir}")
    
    def _validate_output_file(self) -> None:
        """
        Validate that the output file can be written.
        
        Raises:
            ValidationError: If the output file path is invalid.
        """
        if not self.output_file:
            return
            
        output_path = Path(self.output_file)
        output_dir = output_path.parent
        
        # Check if the directory exists
        if not output_dir.exists():
            raise ValidationError(f"Output directory does not exist: {output_dir}")
        
        # Check if the directory is writable
        if not os.access(output_dir, os.W_OK):
            raise ValidationError(f"Output directory is not writable: {output_dir}")
        
        # Check if the file exists and is writable
        if output_path.exists() and not os.access(output_path, os.W_OK):
            raise ValidationError(f"Output file is not writable: {output_path}")
    
    def _render_template(self, agent_config_file: Path) -> str:
        """
        Render the template with the agent configuration.
        
        Args:
            agent_config_file: Path to the agent configuration file.
            
        Returns:
            Rendered template as a string.
            
        Raises:
            TemplateRenderingError: If template rendering fails.
        """
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
        """
        Execute the render command.
        
        Raises:
            Various exceptions depending on what fails.
        """
        logger.info(f"Starting template rendering for agent: {self.agent_name}")
        
        try:
            # Validate inputs
            self._validate_template_directory()
            
            if self.output_file:
                self._validate_output_file()
            
            # Get agent paths
            _, agent_config_file = self._get_agent_paths()
            
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
            
        except FileNotFoundError as e:
            logger.error(f"File not found: {str(e)}")
            raise click.ClickException(f"File not found: {str(e)}")
            
        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            raise click.ClickException(f"Validation error: {str(e)}")
            
        except TemplateRenderingError as e:
            logger.error(f"Template rendering error: {str(e)}")
            raise click.ClickException(f"Template rendering error: {str(e)}")
            
        except Exception as e:
            logger.error(f"Failed to render template for agent {self.agent_name}: {str(e)}", 
                         exc_info=True)
            raise click.ClickException(
                f"Failed to render template for agent {self.agent_name}: {str(e)}"
            )


@click.command()
@click.argument('agent_name')
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
        agent-actions render my_agent
        agent-actions render my_agent -o rendered_output.yml
        agent-actions render my_agent -t custom_templates
    """
    command = RenderCommand(agent_name, output_file, template_dir)
    command.execute()
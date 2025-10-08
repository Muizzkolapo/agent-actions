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

    def _find_workflow_file(self, workflow_name: str) -> Path:
        """
        Find workflow file in standard locations.

        Searches in:
        1. Current directory: ./{workflow_name}.yml
        2. Workflows directory: ./workflows/{workflow_name}.yml
        3. Dev artefacts: ./dev_artefacts/sample_workflows/{workflow_name}.yml

        Args:
            workflow_name: Name of workflow (without extension)

        Returns:
            Path to workflow file

        Raises:
            FileLoadError: If workflow not found in any location
        """
        # Ensure workflow_name doesn't have extension
        workflow_base = workflow_name.replace('.yml', '').replace('.yaml', '')

        search_paths = [
            Path(f"{workflow_base}.yml"),
            Path(f"workflows/{workflow_base}.yml"),
            Path(f"dev_artefacts/sample_workflows/{workflow_base}.yml"),
        ]

        for path in search_paths:
            if path.exists():
                logger.info(f"Found workflow at: {path}")
                return path

        # Not found - raise helpful error
        raise FileLoadError(
            f"Workflow '{workflow_base}.yml' not found",
            context={
                'workflow_name': workflow_base,
                'searched_paths': [str(p) for p in search_paths],
                'current_directory': os.getcwd(),
                'operation': 'find_workflow_file'
            }
        )
    
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
            raise TemplateRenderingError(
                "Failed to render template",
                context={'agent_name': self.args.agent_name, 'config_file': str(agent_config_file), 'template_dir': str(self.template_dir), 'operation': '_render_template'},
                cause=e
            ) from e
    
    def execute(self) -> None:
        """Execute the render command."""
        try:
            # Determine mode: agent or workflow
            if self.args.agent_name:
                self._execute_agent_mode()
            else:
                self._execute_workflow_mode()

        except (FileLoadError, ValidationError, TemplateRenderingError) as e:
            logger.error(f"{e.__class__.__name__}: {str(e)}")
            from agent_actions.core.user_errors import format_user_error
            context = {
                'command': 'render',
                'agent': self.args.agent_name,
                'workflow': self.args.workflow_name
            }
            error_message = format_user_error(e, context)
            raise click.ClickException(error_message)

        except Exception as e:
            target = self.args.agent_name or self.args.workflow_name
            logger.error(f"Failed to render template for {target}: {str(e)}", exc_info=True)
            raise click.ClickException(f"Failed to render template for {target}: {str(e)}")

    def _execute_agent_mode(self) -> None:
        """Execute render in agent mode (existing behavior)."""
        logger.info(f"Starting template rendering for agent: {self.args.agent_name}")

        from agent_actions.tasks.services.project_paths_factory import ProjectPathsFactory
        paths = ProjectPathsFactory.create_project_paths(self.args.agent_name, self.args.agent_name)
        agent_config_file = paths.agent_config_dir / f"{self.args.agent_name}.yml"

        # Render the template
        rendered_template = self._render_template(agent_config_file)

        # Output the result
        self._output_result(rendered_template, 'agent', self.args.agent_name)

    def _execute_workflow_mode(self) -> None:
        """Execute render in workflow mode (new behavior for debugging)."""
        logger.info(f"Starting template rendering for workflow: {self.args.workflow_name}")

        # Find workflow file
        workflow_file = self._find_workflow_file(self.args.workflow_name)

        # Render the template
        rendered_template = self._render_template(workflow_file)

        # Output the result
        self._output_result(rendered_template, 'workflow', self.args.workflow_name)

    def _output_result(self, rendered_template: str, mode: str, name: str) -> None:
        """Output the rendered template to console or file."""
        if not self.args.output_file:
            click.echo(rendered_template)
            logger.info(f"Rendered {mode} template output to console", extra={mode: name})
        else:
            logger.info(f"Rendered {mode} template saved to {self.args.output_file}", extra={mode: name})
            click.echo(f"Template rendered successfully and saved to {self.args.output_file}")


@click.command()
@click.argument('workflow_name', required=False)
@click.option('-a', '--agent', 'agent_name',
              help="Name of the agent to render template for")
@click.option('-o', '--output', 'output_file',
              help="Path to save the rendered template (default: output to console)")
@click.option('-t', '--template-dir',
              help="Directory containing templates (default: ./templates)")
@requires_project
def render(workflow_name: Optional[str] = None, agent_name: Optional[str] = None,
          output_file: Optional[str] = None, template_dir: Optional[str] = None) -> None:
    """
    Render Jinja2 templates in workflow or agent configuration files.

    This command processes configuration files and renders them using Jinja2
    templates in the template directory. Useful for debugging template issues,
    verifying macro expansion, and troubleshooting YAML parsing errors.

    MODES:

    1. Workflow mode (new): Render workflow YAML files for debugging templates
       Usage: agent-actions render <workflow-name>

    2. Agent mode (existing): Render agent configuration files
       Usage: agent-actions render -a <agent-name>

    The output can be saved to a file or displayed in the console.

    Examples:
        # Workflow mode - render workflow templates
        agent-actions render customer_review_analysis_with_loop
        agent-actions render qanalabs-quiz-gen -o rendered.yml

        # Agent mode - render agent config
        agent-actions render -a my_agent
        agent-actions render --agent my_agent -o rendered_output.yml
        agent-actions render -a my_agent -t custom_templates
    """
    try:
        args = RenderCommandArgs(
            agent_name=agent_name,
            workflow_name=workflow_name,
            output_file=output_file,
            template_dir=template_dir
        )
        command = RenderCommand(args)
        command.execute()
    except PydanticValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'render'})
        raise click.ClickException(error_message)

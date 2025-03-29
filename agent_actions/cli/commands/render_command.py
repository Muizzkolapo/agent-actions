
# File: agent_actions/cli/commands/render_command.py
"""
Render command for the Agent Actions CLI.
"""

import os
import click
from pathlib import Path
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.workflow.render_workflow import render_pipeline_with_templates


@click.command()
@click.argument('agent_name')
def render(agent_name: str) -> None:
    """
    Render a Jinja template for the specified agent.

    Args:
        agent_name: Name of the agent template to render.
    """
    try:
        agent_config_dir_str, _, _ = FileHandler.get_agent_paths(agent_name)
        agent_config_dir = Path(agent_config_dir_str)
        agent_config_file_str = FileHandler.find_config_file(str(agent_config_dir), f"{agent_name}.yml")
        
        if not agent_config_file_str:
            raise ValueError(f"Missing configuration file: {agent_name}.yml")

        agent_config_file = Path(agent_config_file_str)
        template_dir = Path(os.getcwd()) / "templates"
        rendered_template = render_pipeline_with_templates(str(agent_config_file), str(template_dir))
        click.echo(rendered_template)
    except Exception as e:
        raise ValueError(f"Failed to render template for agent {agent_name}: {str(e)}")
"""
Initialize command for the Agent Actions CLI.
"""

import click
from typing import Optional
from agent_actions.core.init import ProjectInitializer


@click.command()
@click.argument('project_name')
def init(project_name: str) -> None:
    """
    Initialize a new Agent Actions project.

    Args:
        project_name: Name of the project to create.
    """
    try:
        initializer = ProjectInitializer(project_name)
        initializer.init_project()
    except Exception as e:
        raise ValueError(f"Failed to initialize project {project_name}: {str(e)}")
"""
Clean command for the Agent Actions CLI.
"""

import click
from agent_actions.handlers.agent_handlers import AgentManager


@click.command()
@click.option('-a', '--agent', required=True,
              help="Agent name")
def clean(agent: str) -> None:
    """
    Clean agent directories.

    Args:
        agent: Name of the agent to clean.
    """
    try:
        AgentManager.clean_agent_directories(agent)
    except Exception as e:
        raise ValueError(f"Failed to clean directories for agent {agent}: {str(e)}")
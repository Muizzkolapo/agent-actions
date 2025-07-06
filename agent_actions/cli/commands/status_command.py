"""
Status command for the Agent Actions CLI.

This module provides the implementation of the 'status' command,
which displays the current status of an agent workflow.
"""

import click
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table

from agent_actions.cli.services.project_paths_factory import ProjectPathsFactory

class StatusCommand:
    """Implementation of the status command."""

    def __init__(self, agent: str):
        """
        Initialize the status command.

        Args:
            agent: Name of the agent configuration.
        """
        self.agent_name = Path(agent).stem
        self.console = Console()

    def execute(self) -> None:
        """
        Execute the status command.
        """
        try:
            paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.agent_name)
            status_file = paths.agent_io_dir / ".agent_status.json"

            if not status_file.exists():
                self.console.print(f"[yellow]No status file found for agent '{self.agent_name}'. Has a workflow been run?[/yellow]")
                return

            with open(status_file, 'r') as f:
                status_data = json.load(f)

            table = Table(title=f"Workflow Status for {self.agent_name}")
            table.add_column("Agent Name", justify="left", style="green")
            table.add_column("Status", justify="center", style="yellow")

            for agent, details in status_data.items():
                table.add_row(agent, details.get('status', 'N/A'))

            self.console.print(table)

        except Exception as e:
            raise click.ClickException(f"Failed to get status for agent {self.agent_name}: {str(e)}")


@click.command()
@click.option('-a', '--agent', required=True,
              help="Agent configuration file name without path or extension")
def status(agent: str) -> None:
    """
    Display the status of an agent workflow.
    """
    command = StatusCommand(agent)
    command.execute()

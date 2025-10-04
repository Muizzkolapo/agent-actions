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

from agent_actions.tasks.services.project_paths_factory import ProjectPathsFactory
from agent_actions.agents.validators.status_validator import StatusCommandArgs
from agent_actions.core.cli_decorators import requires_project
from pydantic import ValidationError


class StatusCommand:
    """Implementation of the status command."""

    def __init__(self, args: StatusCommandArgs):
        """
        Initialize the status command.

        Args:
            args: Pydantic model containing the command arguments.
        """
        self.args = args
        self.agent_name = Path(args.agent).stem
        self.console = Console()

    def execute(self) -> None:
        """
        Execute the status command.
        """
        try:
            paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.args.agent)
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
                if details is None:
                    status = 'N/A'
                elif isinstance(details, dict):
                    status = details.get('status', 'N/A')
                else:
                    status = 'N/A'
                table.add_row(agent, status)

            self.console.print(table)

        except Exception as e:
            from agent_actions.core.user_errors import format_user_error
            error_message = format_user_error(e, {'command': 'status', 'agent': self.agent_name})
            raise click.ClickException(error_message)


@click.command()
@click.option('-a', '--agent', required=True,
              help="Agent configuration file name without path or extension")
@requires_project
def status(agent: str) -> None:
    """
    Display the status of an agent workflow.
    """
    try:
        args = StatusCommandArgs(agent=agent)
        command = StatusCommand(args)
        command.execute()
    except ValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'status'})
        raise click.ClickException(error_message)

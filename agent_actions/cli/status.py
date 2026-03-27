"""Status command for the Agent Actions CLI."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.validation.status_validator import StatusCommandArgs


class StatusCommand:
    def __init__(self, args: StatusCommandArgs):
        self.args = args
        self.agent_name = Path(args.agent).stem
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.args.agent, auto_create=False, project_root=project_root
        )
        status_file = paths.io_dir / ".agent_status.json"
        if not status_file.exists():
            self.console.print(
                f"[yellow]No status file found for agent '{self.agent_name}'. "
                "Has a workflow been run?[/yellow]"
            )
            return
        try:
            with open(status_file, encoding="utf-8") as f:
                status_data = json.load(f)
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Status file is corrupted: {status_file}\n{e}") from e
        if not isinstance(status_data, dict):
            raise click.ClickException(
                f"Status file has unexpected format (expected JSON object): {status_file}"
            )
        table = Table(title=f"Workflow Status for {self.agent_name}")
        table.add_column("Agent Name", justify="left", style="green")
        table.add_column("Status", justify="center", style="yellow")
        for agent, details in status_data.items():
            if details is None:
                workflow_status = "N/A"
            elif isinstance(details, dict):
                workflow_status = details.get("status", "N/A")
            else:
                workflow_status = "N/A"
            table.add_row(agent, workflow_status)
        self.console.print(table)


@click.command()
@click.option(
    "-a", "--agent", required=True, help="Agent configuration file name without path or extension"
)
@handles_user_errors("status")
@requires_project
def status(agent: str, project_root: Path | None = None) -> None:
    """Display the status of an agent workflow."""
    args = StatusCommandArgs(agent=agent)
    command = StatusCommand(args)
    command.execute(project_root=project_root)

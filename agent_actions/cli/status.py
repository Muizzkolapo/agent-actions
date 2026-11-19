"""Status command for the Agent Actions CLI."""

import json
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from agent_actions.cli.args import StatusCommandArgs
from agent_actions.cli.cli_decorators import (
    handles_user_errors,
    requires_project,
    workflow_option,
)
from agent_actions.cli.exit_codes import run_status as status_of_the_run
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.workflow.managers.state import (
    COMPLETED_STATUSES,
    TERMINAL_STATUSES,
    ActionStatus,
)


class _StoredStatuses:
    """The stored statuses, answering what ``exit_codes.run_status`` asks of a state manager."""

    def __init__(self, statuses: list[Any]):
        self._statuses = statuses

    def is_workflow_complete(self) -> bool:
        return all(status in COMPLETED_STATUSES for status in self._statuses)

    def is_workflow_done(self) -> bool:
        return all(status in TERMINAL_STATUSES for status in self._statuses)

    def has_any_failed(self) -> bool:
        return ActionStatus.FAILED in self._statuses


def status_report(agent: str, project_root: Path | None = None) -> dict[str, Any]:
    """What ``agac status --json`` prints: each stored action status, and the run's.

    Scripts read this shape, so its keys stay as they are. ``run_status`` is None when
    no action status is stored: the workflow has not run.
    """
    workflow = Path(agent).stem
    paths = ProjectPathsFactory.create_project_paths(
        workflow, agent, auto_create=False, project_root=project_root
    )
    status_file = paths.io_dir / ".agent_status.json"
    try:
        with open(status_file, encoding="utf-8") as f:
            status_data = json.load(f)
    except FileNotFoundError:
        status_data = {}
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Status file is corrupted: {status_file}\n{e}") from e
    if not isinstance(status_data, dict):
        raise click.ClickException(
            f"Status file has unexpected format (expected JSON object): {status_file}"
        )
    actions = [
        {
            "name": name,
            "status": details.get("status") if isinstance(details, dict) else None,
            "error": _error_of(details) if isinstance(details, dict) else None,
        }
        for name, details in status_data.items()
    ]
    run_status = (
        status_of_the_run(_StoredStatuses([action["status"] for action in actions]))
        if actions
        else None
    )
    return {"workflow": workflow, "run_status": run_status, "actions": actions}


class StatusCommand:
    def __init__(self, args: StatusCommandArgs):
        self.args = args
        self.agent_name = Path(args.agent).stem
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        report = status_report(self.args.agent, project_root)
        if self.args.as_json:
            if report["run_status"] is None:
                click.echo(self._never_ran(), err=True)
            click.echo(json.dumps(report, indent=2, ensure_ascii=False))
            return
        if report["run_status"] is None:
            self.console.print(f"[yellow]{self._never_ran()}[/yellow]")
            return
        rows = [
            (action["name"], action["status"] or "N/A", _first_line(action["error"]))
            for action in report["actions"]
        ]
        table = Table(title=f"Workflow Status for {self.agent_name}")
        table.add_column("Agent Name", justify="left", style="green")
        table.add_column("Status", justify="center", style="yellow")
        with_errors = any(error for *_, error in rows)
        if with_errors:
            table.add_column("Error", justify="left", style="red", overflow="fold")
        for agent, workflow_status, error in rows:
            table.add_row(agent, workflow_status, *([error] if with_errors else []))
        self.console.print(table)

    def _never_ran(self) -> str:
        return f"No action status is stored for workflow '{self.agent_name}'. Has it been run?"


_ERROR_SHOWN = 200


def _error_of(details: dict) -> str | None:
    """A failed action's ``error_message``; None for any other action."""
    message = details.get("error_message")
    if details.get("status") != "failed" or not isinstance(message, str) or not message.strip():
        return None
    return message


def _first_line(error: str | None) -> str:
    """The first line of an error, cut short for the table; nothing when there is none."""
    if error is None:
        return ""
    first = error.strip().splitlines()[0]
    return first if len(first) <= _ERROR_SHOWN else first[: _ERROR_SHOWN - 1] + "…"


@click.command()
@workflow_option()
@click.option(
    "--json", "as_json", is_flag=True, help="Print each action's status and the run's as JSON"
)
@handles_user_errors("status")
@requires_project
def status(agent: str, as_json: bool, project_root: Path | None = None) -> None:
    """Display the status of an agent workflow."""
    args = StatusCommandArgs(agent=agent, as_json=as_json)
    command = StatusCommand(args)
    command.execute(project_root=project_root)

"""Dispositions command — inspect record-level processing outcomes per action.

Shows per-action breakdown of record dispositions (success, failed,
exhausted, quarantined, etc.) to help diagnose workflow issues and
identify records that need retry.
"""

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.record.reasons import HALTED_ON_EXHAUSTED
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import (
    FAILURE_DISPOSITIONS,
    NODE_LEVEL_RECORD_ID,
)

logger = logging.getLogger(__name__)


class DispositionsCommand:
    """Display per-action disposition breakdown for a workflow."""

    def __init__(self, agent: str, action: str | None, quarantined: bool):
        self.agent_name = Path(agent).stem
        self.agent = agent
        self.action_filter = action
        self.quarantined_only = quarantined
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.agent, auto_create=False, project_root=project_root
        )

        backend = get_storage_backend(
            workflow_path=str(paths.io_dir.parent),
            workflow_name=self.agent_name,
        )
        backend.initialize()

        workflow = load_workflow(self.agent_name, paths, project_root, read_only=True)
        execution_order = list(workflow.execution_order)

        if self.action_filter:
            if self.action_filter not in execution_order:
                raise click.ClickException(
                    f"Action '{self.action_filter}' not in execution order: {execution_order}"
                )
            actions = [self.action_filter]
        else:
            actions = execution_order

        if self.quarantined_only:
            self._show_quarantined(backend, actions)
        else:
            self._show_summary(backend, actions)

    def _show_summary(self, backend, actions: list[str]) -> None:
        """Show per-action disposition counts beside the records produced."""
        table = Table(title=f"Dispositions: {self.agent_name}")
        table.add_column("Action", style="cyan")
        table.add_column("Success", justify="right", style="green")
        table.add_column("Failed", justify="right", style="red")
        table.add_column("Exhausted", justify="right", style="red")
        table.add_column("Unprocessed", justify="right", style="yellow")
        table.add_column("Passthrough", justify="right", style="dim")
        table.add_column("Filtered", justify="right", style="dim")
        table.add_column("Total", justify="right", style="bold")
        table.add_column("Records", justify="right", style="bold")

        produced = self._records_written(backend)

        for action in actions:
            rows = backend.get_disposition(action)
            rows = [r for r in rows if r.get("record_id") != NODE_LEVEL_RECORD_ID]

            counts: dict[str, int] = {}
            for row in rows:
                disp = row.get("disposition", "unknown")
                counts[disp] = counts.get(disp, 0) + 1

            total = sum(counts.values())
            if total == 0:
                continue

            table.add_row(
                action,
                str(counts.get("success", 0)),
                str(counts.get("failed", 0)),
                str(counts.get("exhausted", 0)),
                str(counts.get("unprocessed", 0)),
                str(counts.get("passthrough", 0)),
                str(counts.get("filtered", 0)),
                str(total),
                str(produced.get(action, 0)),
            )

        action_level = self._action_level_rows(backend, actions)

        if table.row_count:
            self.console.print(table)
            self.console.print(
                "[dim]Total counts the input records the action consumed, one "
                "disposition each; Records counts the records now stored under "
                "it. They differ when an action expands or collapses "
                "records.[/dim]"
            )
        elif not action_level:
            self.console.print("[dim]No dispositions recorded. Has the workflow been run?[/dim]")

        self._show_action_level(action_level)

    @staticmethod
    def _records_written(backend) -> dict[str, int]:
        """Records each action wrote, by action name.

        Absence is reported as zero rather than crashing the summary — this is
        context beside the dispositions, not the thing being asked for.
        """
        try:
            return dict(backend.get_storage_stats().get("nodes") or {})
        except Exception:
            logger.debug("Could not read per-action record counts", exc_info=True)
            return {}

    @staticmethod
    def _action_level_rows(backend, actions: list[str]) -> list[tuple[str, dict]]:
        """Node-level dispositions, which describe the action rather than a record."""
        found = []
        for action in actions:
            for row in backend.get_disposition(action, record_id=NODE_LEVEL_RECORD_ID):
                found.append((action, row))
        return found

    def _show_action_level(self, rows: list[tuple[str, dict]]) -> None:
        """Render action-level state, which the per-record table cannot show.

        Without this an action whose only row is a halt is absent from the
        output entirely, since the summary skips actions with no record rows.
        """
        if not rows:
            return
        table = Table(title="Action-level state")
        table.add_column("Action", style="cyan")
        table.add_column("State", style="red")
        table.add_column("Reason")

        halted = False
        for action, row in rows:
            state = row.get("disposition", "unknown")
            if row.get("detail") == HALTED_ON_EXHAUSTED:
                state = f"{state} (halted)"
                halted = True
            table.add_row(action, state, (row.get("reason") or "")[:100])

        self.console.print(table)
        if halted:
            self.console.print(
                "[yellow]A halted action is not re-run by 'agac run'. Resume it with "
                "'agac retry', or start over with 'agac run --fresh'.[/yellow]"
            )

    def _show_quarantined(self, backend, actions: list[str]) -> None:
        """Show details of failed/exhausted/unprocessed records."""
        table = Table(title=f"Quarantined Records: {self.agent_name}")
        table.add_column("Action", style="cyan")
        table.add_column("Record ID", style="red")
        table.add_column("Disposition", style="yellow")
        table.add_column("Reason", style="dim", max_width=60)

        found = 0
        for action in actions:
            rows = backend.get_disposition(action)
            for row in rows:
                if row.get("record_id") == NODE_LEVEL_RECORD_ID:
                    continue
                if row.get("disposition") not in FAILURE_DISPOSITIONS:
                    continue
                found += 1
                table.add_row(
                    action,
                    row.get("record_id", "?"),
                    row.get("disposition", "?"),
                    (row.get("reason") or "")[:60],
                )

        action_level = self._action_level_rows(backend, actions)

        if found:
            self.console.print(table)
        elif not action_level:
            self.console.print("[green]No quarantined records found.[/green]")

        self._show_action_level(action_level)


@click.command()
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Agent configuration file name without path or extension",
)
@click.option(
    "--action",
    default=None,
    help="Show dispositions for a specific action only.",
)
@click.option(
    "--quarantined",
    is_flag=True,
    default=False,
    help="Show only failed/exhausted/unprocessed records with details.",
)
@handles_user_errors("dispositions")
@requires_project
def dispositions(
    agent: str,
    action: str | None,
    quarantined: bool,
    project_root: Path | None = None,
) -> None:
    """Inspect record-level processing dispositions per action."""
    command = DispositionsCommand(agent, action, quarantined)
    command.execute(project_root=project_root)

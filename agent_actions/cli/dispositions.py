"""Dispositions command — inspect record-level processing outcomes per action.

Shows per-action breakdown of record dispositions (success, failed,
exhausted, quarantined, etc.) to help diagnose workflow issues and
identify records that need retry.
"""

import json
import logging
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from agent_actions.cli.cli_decorators import (
    handles_user_errors,
    requires_project,
    workflow_option,
)
from agent_actions.cli.renderers.whole_table import print_whole
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.record.reasons import (
    EXPECTATIONS_FAILED,
    GUARD_SKIP_REASONS,
    HALTED_ON_EXHAUSTED,
    SENT_ELSEWHERE,
)
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
    FAILURE_DISPOSITIONS,
    NODE_LEVEL_RECORD_ID,
)

logger = logging.getLogger(__name__)

# What --quarantined lists: the failures retry acts on, and the records no answer reached.
QUARANTINED_DISPOSITIONS = FAILURE_DISPOSITIONS | {DISPOSITION_UNPROCESSED}

# Wide enough that measuring a table at it never shrinks a column.

# The summary's count columns in order: the key --json prints each as, its header, its style.
TABLE_COUNTS = {
    "success": ("Success", "green"),
    "failed_checks": ("Failed checks", "yellow"),
    "failed": ("Failed", "red"),
    "exhausted": ("Exhausted", "red"),
    "guard_skipped": ("Guard skipped", "yellow"),
    "unprocessed": ("Unprocessed", "yellow"),
    "passthrough": ("Passthrough", "dim"),
    "filtered": ("Filtered", "dim"),
}
# Every count --json prints: the table's, then the dispositions it has no column for.
COUNT_KEYS = (*TABLE_COUNTS, DISPOSITION_SKIPPED, DISPOSITION_DEFERRED)


def _counts(rows: list[dict]) -> dict[str, int]:
    """An action's record rows under every key of ``COUNT_KEYS``; they add up to the rows."""
    held: dict[str, int] = {}
    for row in rows:
        disposition = row.get("disposition", "unknown")
        held[disposition] = held.get(disposition, 0) + 1
    guard_skipped = sum(
        1
        for row in rows
        if row.get("disposition") == DISPOSITION_UNPROCESSED
        and row.get("reason") in GUARD_SKIP_REASONS
    )
    failed_checks = sum(
        1
        for row in rows
        if row.get("disposition") == DISPOSITION_SUCCESS
        and row.get("reason") == EXPECTATIONS_FAILED
    )
    return {
        "success": held.get(DISPOSITION_SUCCESS, 0) - failed_checks,
        "failed_checks": failed_checks,
        "failed": held.get(DISPOSITION_FAILED, 0),
        "exhausted": held.get(DISPOSITION_EXHAUSTED, 0),
        "guard_skipped": guard_skipped,
        "unprocessed": held.get(DISPOSITION_UNPROCESSED, 0) - guard_skipped,
        "passthrough": held.get(DISPOSITION_PASSTHROUGH, 0),
        "filtered": held.get(DISPOSITION_FILTERED, 0),
        "skipped": held.get(DISPOSITION_SKIPPED, 0),
        "deferred": held.get(DISPOSITION_DEFERRED, 0),
    }


def dispositions_report(backend, workflow: str, actions: list[str]) -> dict[str, Any]:
    """What ``agac dispositions --json`` prints: every count of each of *actions*.

    Scripts read this shape, so its keys stay as they are and every count is there,
    0 where the action holds none. ``records`` is None when the store cannot count
    them. An action's own row (``__node__``) is not a record: it is in ``action_level``.
    A record the action sent to another branch is counted in ``sent_elsewhere``, outside
    ``counts`` and ``total``, as the table shows it.
    """
    stored = DispositionsCommand._records_stored(backend)
    entries = []
    for action in actions:
        rows = backend.get_disposition(action, snapshots=False)
        held = [row for row in rows if row.get("record_id") != NODE_LEVEL_RECORD_ID]
        records = [row for row in held if not _sent_elsewhere(row)]
        entries.append(
            {
                "name": action,
                "counts": _counts(records),
                "total": len(records),
                "sent_elsewhere": len(held) - len(records),
                "records": None if stored is None else stored.get(action, 0),
                "action_level": [
                    {
                        "state": row.get("disposition", "unknown"),
                        "halted": row.get("detail") == HALTED_ON_EXHAUSTED,
                        "reason": row.get("reason"),
                    }
                    for row in rows
                    if row.get("record_id") == NODE_LEVEL_RECORD_ID
                ],
            }
        )
    return {"workflow": workflow, "actions": entries}


class DispositionsCommand:
    """Display per-action disposition breakdown for a workflow."""

    def __init__(self, agent: str, action: str | None, quarantined: bool, as_json: bool = False):
        self.agent_name = Path(agent).stem
        self.agent = agent
        self.action_filter = action
        self.quarantined_only = quarantined
        self.as_json = as_json
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

        workflow = load_workflow(
            self.agent_name, paths, project_root, sends_requests=False, read_only=True
        )
        execution_order = list(workflow.execution_order)

        if self.action_filter:
            if self.action_filter not in execution_order:
                raise click.ClickException(
                    f"Action '{self.action_filter}' not in execution order: {execution_order}"
                )
            actions = [self.action_filter]
        else:
            actions = execution_order

        if self.as_json:
            report = dispositions_report(backend, self.agent_name, actions)
            click.echo(json.dumps(report, indent=2, ensure_ascii=False))
        elif self.quarantined_only:
            self._show_quarantined(backend, actions)
        else:
            self._show_summary(backend, actions)

    def _show_summary(self, backend, actions: list[str]) -> None:
        """Show per-action disposition counts beside the records produced."""
        table = Table(title=f"Dispositions: {self.agent_name}")
        table.add_column("Action", style="cyan")
        for header, style in TABLE_COUNTS.values():
            table.add_column(header, justify="right", style=style)
        entries = dispositions_report(backend, self.agent_name, actions)["actions"]
        show_sent = any(entry["sent_elsewhere"] for entry in entries)
        if show_sent:
            table.add_column("Sent elsewhere", justify="right", style="dim")
        table.add_column("Total", justify="right", style="bold")
        table.add_column("Records", justify="right", style="bold")

        for entry in entries:
            if entry["total"] == 0 and not entry["sent_elsewhere"]:
                continue
            table.add_row(
                entry["name"],
                *(str(entry["counts"][key]) for key in TABLE_COUNTS),
                *([str(entry["sent_elsewhere"])] if show_sent else []),
                str(entry["total"]),
                "?" if entry["records"] is None else str(entry["records"]),
            )

        action_level = self._action_level_rows(backend, actions)

        if table.row_count:
            print_whole(self.console, table)
            self.console.print(
                "[dim]Total counts the input records the action consumed, one "
                "disposition each; Records counts what is stored under it now. "
                "The two differ when an action expands or collapses records, "
                "and while its output is unwritten — a batch in flight, or a "
                "run that stopped early. Guard skipped counts the records the "
                "action's guard skipped: they are stored as unprocessed, so a later "
                "run sends them again once the guard passes, and --quarantined lists "
                "them with that reason. Failed checks counts the records shipped "
                "with a verdict that did not pass (on_exhausted: return_last, "
                "repair: none): they are stored as successes, so nothing reading them "
                "is blocked and retry does not re-run them."
                + (
                    " Sent elsewhere counts the records the action's guard sent to "
                    "another branch: they are not the action's, so not in its Total."
                    if show_sent
                    else ""
                )
                + "[/dim]"
            )
        elif not action_level:
            self.console.print("[dim]No dispositions recorded. Has the workflow been run?[/dim]")

        self._show_action_level(action_level)

    @staticmethod
    def _records_stored(backend) -> dict[str, int] | None:
        """Records stored per action, or None when the count is unavailable.

        None is not zero: reporting a failed lookup as zero would show an
        action that fanned one record into five as having produced nothing,
        which is the reading this column exists to prevent.
        """
        try:
            return dict(backend.get_storage_stats().get("nodes") or {})
        except Exception:
            logger.warning("Could not read per-action record counts — showing '?'", exc_info=True)
            return None

    @staticmethod
    def _action_level_rows(backend, actions: list[str]) -> list[tuple[str, dict]]:
        """Node-level dispositions, which describe the action rather than a record."""
        found = []
        for action in actions:
            for row in backend.get_disposition(
                action, record_id=NODE_LEVEL_RECORD_ID, snapshots=False
            ):
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
            table.add_row(action, state, Text((row.get("reason") or "")[:100]))

        print_whole(self.console, table)
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
            rows = backend.get_disposition(action, snapshots=False)
            for row in rows:
                if row.get("record_id") == NODE_LEVEL_RECORD_ID:
                    continue
                if row.get("disposition") not in QUARANTINED_DISPOSITIONS:
                    continue
                found += 1
                table.add_row(
                    action,
                    row.get("record_id", "?"),
                    row.get("disposition", "?"),
                    Text((row.get("reason") or "")[:60]),
                )

        action_level = self._action_level_rows(backend, actions)

        if found:
            print_whole(self.console, table)
        elif not action_level:
            self.console.print("[green]No quarantined records found.[/green]")

        self._show_action_level(action_level)


@click.command()
@workflow_option()
@click.option(
    "-A",
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
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the count of each disposition per action as JSON",
)
@handles_user_errors("dispositions")
@requires_project
def dispositions(
    agent: str,
    action: str | None,
    quarantined: bool,
    as_json: bool,
    project_root: Path | None = None,
) -> None:
    """Inspect record-level processing dispositions per action."""
    if as_json and quarantined:
        raise click.UsageError(
            "--json prints the counts, so it takes no --quarantined. "
            "'agac records --snapshots' prints the failed and exhausted records as JSON."
        )
    command = DispositionsCommand(agent, action, quarantined, as_json)
    command.execute(project_root=project_root)


def _sent_elsewhere(row: dict) -> bool:
    return row.get("disposition") == DISPOSITION_FILTERED and row.get("reason") == SENT_ELSEWHERE

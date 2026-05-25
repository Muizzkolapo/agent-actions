"""Retry command for the Agent Actions CLI.

Retries failed/exhausted records from a specific action forward.
Uses the disposition table to identify what failed and delegates to
the existing workflow execution engine for re-processing.
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import (
    FAILURE_DISPOSITIONS,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.validation.retry_validator import RetryCommandArgs

logger = logging.getLogger(__name__)

_RETRY_MANIFEST_NAME = "_retry_manifest.json"


def _manifest_path(store_dir: Path) -> Path:
    """Return the retry manifest file path within the workflow store directory."""
    return store_dir / _RETRY_MANIFEST_NAME


def _write_manifest(
    path: Path,
    from_action: str,
    record_ids: list[str],
    downstream_actions: list[str],
    dispositions: list[dict],
) -> None:
    """Write a retry manifest before clearing dispositions."""
    manifest = {
        "from_action": from_action,
        "record_ids": sorted(record_ids),
        "downstream_actions": downstream_actions,
        "dispositions": dispositions,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, manifest, indent=2)


def _read_manifest(path: Path) -> dict[str, Any] | None:
    """Read and return the retry manifest, or None if absent/corrupt."""
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Corrupt retry manifest at %s: %s — ignoring", path, e)
        return None


def _delete_manifest(path: Path) -> None:
    """Delete the retry manifest after successful completion."""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Could not delete retry manifest %s: %s", path, e)


class RetryCommand:
    """Retry failed/exhausted records from a given action forward."""

    def __init__(self, args: RetryCommandArgs):
        self.args = args
        self.agent_name = Path(args.agent).stem
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.args.agent, auto_create=False, project_root=project_root
        )

        backend = get_storage_backend(
            workflow_path=str(paths.io_dir.parent),
            workflow_name=self.agent_name,
        )
        backend.initialize()

        store_dir = paths.io_dir / "store" / self.agent_name
        manifest_file = _manifest_path(store_dir)
        prior_manifest = _read_manifest(manifest_file)

        if prior_manifest:
            self.console.print(
                "[yellow]Found incomplete retry manifest — "
                "prior retry was interrupted. Restoring dispositions...[/yellow]"
            )
            disposition_rows = prior_manifest.get("dispositions", [])
            for row in disposition_rows:
                backend.set_disposition(
                    row["action_name"],
                    row["record_id"],
                    row["disposition"],
                    reason=row.get("reason"),
                    detail=row.get("detail"),
                    input_snapshot=row.get("input_snapshot"),
                )
            _delete_manifest(manifest_file)
            self.console.print(
                f"[cyan]Restored {len(disposition_rows)} disposition(s). "
                f"Proceeding with retry.[/cyan]"
            )

        workflow = load_workflow(self.agent_name, paths, project_root)
        execution_order = list(workflow.execution_order)

        failures = self._find_failures(backend, execution_order)

        if not failures:
            self.console.print(
                "[green]No failed or exhausted records found. Nothing to retry.[/green]"
            )
            return

        from_action = self.args.from_action
        if from_action:
            if from_action not in execution_order:
                raise click.ClickException(
                    f"Action '{from_action}' not found in execution order: {execution_order}"
                )
        else:
            for action in execution_order:
                if action in failures:
                    from_action = action
                    break

        if not from_action:
            self.console.print("[green]No actionable failures found.[/green]")
            return

        target_records = failures.get(from_action, [])
        if not target_records:
            self.console.print(
                f"[yellow]No failed records at action '{from_action}'. Nothing to retry.[/yellow]"
            )
            return
        if self.args.record:
            target_records = [r for r in target_records if r["record_id"] == self.args.record]
            if not target_records:
                raise click.ClickException(
                    f"Record '{self.args.record}' not found in failed records "
                    f"for action '{from_action}'"
                )

        self._display_retry_plan(from_action, target_records, execution_order, failures)

        if self.args.dry_run:
            self.console.print("\n[yellow]Dry run — no changes made.[/yellow]")
            return

        from_idx = execution_order.index(from_action)
        downstream_actions = execution_order[from_idx:]
        record_ids = {r["record_id"] for r in target_records}

        logger.info(
            "Clearing dispositions for retry: records=%s, actions=%s. "
            "If the re-run fails, run 'retry' again to resume.",
            sorted(record_ids),
            downstream_actions,
        )

        # Snapshot dispositions BEFORE clearing — this is the crash-recovery payload.
        snapshot_dispositions: list[dict] = []
        for action in downstream_actions:
            rows = backend.get_disposition(action)
            snapshot_dispositions.extend(r for r in rows if r.get("record_id") in record_ids)

        # Write manifest — if this fails, we abort (no dispositions cleared).
        _write_manifest(
            manifest_file,
            from_action,
            list(record_ids),
            downstream_actions,
            snapshot_dispositions,
        )

        cleared = 0
        for action in downstream_actions:
            for record_id in record_ids:
                cleared += backend.clear_disposition(action, record_id=record_id)
            # Clear node-level disposition so the executor doesn't see a
            # stale action-level FAILED/SKIPPED signal.
            backend.clear_disposition(action, record_id=NODE_LEVEL_RECORD_ID)

        self.console.print(
            f"\n[cyan]Cleared {cleared} disposition(s) for {len(record_ids)} record(s) "
            f"across {len(downstream_actions)} action(s).[/cyan]"
        )

        self.console.print("\n[bold]Re-running workflow...[/bold]\n")

        # Reset action-level status for downstream actions to PENDING so the
        # coordinator doesn't skip them as "already completed."
        # Deferred import: avoid circular import at module load time.
        from agent_actions.workflow.managers.state import ActionStatus

        state_mgr = workflow.services.core.state_manager
        for action in downstream_actions:
            state_mgr.update_status(action, ActionStatus.PENDING)

        workflow.run()

        # Retry completed successfully — delete the manifest.
        _delete_manifest(manifest_file)

        self.console.print("\n[green]Retry complete.[/green]")

    @staticmethod
    def _find_failures(
        backend,
        execution_order: list[str],
    ) -> dict[str, list[dict]]:
        """Query disposition table for failed/exhausted records per action."""
        failures: dict[str, list[dict]] = {}
        for action in execution_order:
            rows = backend.get_disposition(action)
            action_failures = [r for r in rows if r.get("disposition") in FAILURE_DISPOSITIONS]
            if action_failures:
                failures[action] = action_failures
        return failures

    def _display_retry_plan(
        self,
        from_action: str,
        target_records: list[dict],
        execution_order: list[str],
        all_failures: dict[str, list[dict]],
    ) -> None:
        """Display what will be retried."""
        from_idx = execution_order.index(from_action)
        downstream = execution_order[from_idx:]

        self.console.print("\n[bold]Retry Plan[/bold]")
        self.console.print(f"  From action: [cyan]{from_action}[/cyan]")
        self.console.print(f"  Actions to re-run: {' → '.join(downstream)}")
        self.console.print(f"  Records to retry: {len(target_records)}")

        table = Table(title="Failed Records")
        table.add_column("Record ID", style="red")
        table.add_column("Disposition", style="yellow")
        table.add_column("Reason", style="dim", max_width=60)

        for record in target_records:
            table.add_row(
                record.get("record_id", "?"),
                record.get("disposition", "?"),
                (record.get("reason") or "")[:60],
            )

        self.console.print(table)

        # Alert user if there are failures at other actions too
        other_actions = [a for a in all_failures if a != from_action]
        if other_actions:
            self.console.print(
                f"\n[dim]Note: failures also exist at: {', '.join(other_actions)}. "
                f"Run 'retry' again after this completes to address them.[/dim]"
            )


@click.command()
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Agent configuration file name without path or extension",
)
@click.option(
    "--from",
    "from_action",
    default=None,
    help="Action to retry from. If omitted, retries from earliest failure.",
)
@click.option(
    "--record",
    default=None,
    help="Restrict retry to a single record (by source_guid) at the --from action.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be retried without executing.",
)
@handles_user_errors("retry")
@requires_project
def retry(
    agent: str,
    from_action: str | None,
    record: str | None,
    dry_run: bool,
    project_root: Path | None = None,
) -> None:
    """Retry failed/exhausted records from a specific action forward."""
    args = RetryCommandArgs(
        agent=agent,
        from_action=from_action,
        record=record,
        dry_run=dry_run,
    )
    command = RetryCommand(args)
    command.execute(project_root=project_root)

"""``agac retry --filter``: keep failed records out of a workflow without retrying them."""

import datetime
import logging
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand, _manifest_path, _read_manifest
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import (
    DISPOSITION_FILTERED,
    DISPOSITION_UNPROCESSED,
    FAILURE_DISPOSITIONS,
    NODE_LEVEL_RECORD_ID,
    DispositionRow,
)
from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.workflow.pipeline import _actions_below

logger = logging.getLogger(__name__)


class RetryFilterCommand:
    """Mark failed records ``filtered``, as a guard's ``on_false: filter`` leaves them.

    The actions below lose what the failure cascaded into them, their ``unprocessed``
    row and tombstone, as they would hold nothing under the guard. The filtered action
    keeps its tombstone: a run carrying the record forward re-asks one it holds no row
    for. A live retry manifest is changed to match, so resuming its retry keeps the filter.
    """

    def __init__(self, args: RetryCommandArgs):
        self.args = args
        self.agent_name = Path(args.agent).stem
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.args.agent, auto_create=False, project_root=project_root
        )
        backend = get_storage_backend(
            workflow_path=str(paths.io_dir.parent), workflow_name=self.agent_name
        )
        backend.initialize()
        manifest_file = _manifest_path(paths.io_dir / "store" / self.agent_name)
        manifest = _read_manifest(manifest_file)

        workflow = load_workflow(self.agent_name, paths, project_root, read_only=True)
        execution_order = list(workflow.execution_order)
        state_mgr = workflow.services.core.state_manager

        # A record an interrupted retry cleared is still failed: resuming it puts the
        # failure back, and so this reads what that restore would put back as written.
        resumed = RetryCommand._left_by_an_interrupted_retry(manifest, state_mgr)
        restoring = RetryCommand._snapshot_to_restore(manifest, resumed, state_mgr)

        targets = list(dict.fromkeys(self.args.filters))
        held = {
            target: self._held(backend, *target, restoring)
            for target in targets
            if target[0] in execution_order
        }
        refusals = [self._refusal(target, held.get(target), execution_order) for target in targets]
        refusals = [refusal for refusal in refusals if refusal]
        if refusals:
            raise click.ClickException(
                "Nothing was filtered:\n" + "\n".join(f"  {r}" for r in refusals)
            )

        listing = "\n".join(f"  {action} / {record_id}" for action, record_id in targets)
        if self.args.dry_run:
            self.console.print(f"[yellow]Dry run — would filter {len(targets)} record(s):[/yellow]")
            self.console.print(listing, markup=False, highlight=False)
            return

        below = {action: self._readers_of(backend, action) for action, _ in targets}
        stored = {
            action: {guid for guid, _ in backend.target_row_identities(action)}
            for action in dict.fromkeys(action for action, _ in targets)
        }
        unstored = [target for target in targets if target[1] not in stored[target[0]]]
        detail = (
            "filtered by hand with agac retry --filter on "
            f"{datetime.datetime.now(datetime.UTC).date().isoformat()}"
        )
        rows: list[DispositionRow] = [
            (
                action,
                record_id,
                DISPOSITION_FILTERED,
                self.args.reason,
                (held[(action, record_id)] or {}).get("relative_path"),
                None,
                detail,
            )
            for action, record_id in targets
        ]

        # The manifest first: a restore replaying it after an interruption here
        # then completes the filter instead of undoing it.
        manifest_changed = manifest is not None and self._filter_the_manifest(
            manifest_file, manifest, rows, below
        )

        backend.set_dispositions_batch(rows)
        dropped = 0
        for action, record_id in targets:
            for reader in below[action]:
                backend.clear_disposition(
                    reader, disposition=DISPOSITION_UNPROCESSED, record_id=record_id
                )
                backend.clear_checkpoint_records(reader, source_guids={record_id})
                dropped += self._drop_tombstones(backend, reader, record_id)

        # Deferred import: avoid circular import at module load time.
        from agent_actions.workflow.managers.state import ActionStatus

        for action in dict.fromkeys(action for action, _ in targets):
            if state_mgr.get_status(
                action
            ) == ActionStatus.COMPLETED_WITH_FAILURES and not backend.get_failed_items(action):
                state_mgr.update_status(action, ActionStatus.COMPLETED)

        logger.info("Filtered by hand: %s (reason: %s)", targets, self.args.reason)
        self.console.print(
            f"[green]Filtered {len(targets)} record(s); no retry selects them again:[/green]"
        )
        self.console.print(listing, markup=False, highlight=False)
        if dropped:
            self.console.print(
                f"[cyan]Removed {dropped} tombstone row(s) their failure left in the actions "
                "below.[/cyan]"
            )
        if unstored:
            # The carry-forward re-asks a carried record it finds no row for.
            self.console.print(
                f"[yellow]{len(unstored)} of them hold no stored row at their action: every "
                "record of their file failed there, so the file was never written. A retry "
                "of other records leaves them filtered, but a run that processes the file "
                "again asks them again, as `agac run` or `agac retry` does while the action "
                "is failed as a whole. To keep them out for good, remove them from the input "
                "in agent_io/staging/:[/yellow]"
            )
            self.console.print(
                "\n".join(f"  {action} / {record_id}" for action, record_id in unstored),
                markup=False,
                highlight=False,
            )
        if manifest_changed:
            self.console.print(
                f"[cyan]Updated the interrupted retry's manifest ({manifest_file}) to match, "
                "so resuming it keeps the filter.[/cyan]",
                highlight=False,
            )

    @staticmethod
    def _held(backend, action: str, record_id: str, restoring: list[dict]) -> dict[str, Any] | None:
        """The disposition *record_id* holds at *action*, read as a restore would leave it."""
        for row in restoring:
            if (row["action_name"], row["record_id"]) == (action, record_id):
                return row
        live = backend.get_disposition(action, record_id=record_id, snapshots=False)
        return live[-1] if live else None

    def _refusal(
        self, target: tuple[str, str], held: dict[str, Any] | None, execution_order: list[str]
    ) -> str | None:
        action, record_id = target
        listed = f"agac dispositions -a {self.agent_name} --action {action} --quarantined"
        if action not in execution_order:
            return (
                f"Action '{action}' is not in workflow '{self.agent_name}'; its actions are "
                f"{', '.join(execution_order)}."
            )
        if record_id == NODE_LEVEL_RECORD_ID:
            return (
                f"'{NODE_LEVEL_RECORD_ID}' is the status of '{action}' itself, not a record. "
                f"Filter its records instead; `{listed}` lists them."
            )
        if held is None:
            return (
                f"Record '{record_id}' holds no disposition at '{action}'. Use an id from "
                f"the Record ID column of `{listed}`."
            )
        if held.get("disposition") not in FAILURE_DISPOSITIONS:
            return (
                f"Record '{record_id}' is {held.get('disposition')} at '{action}', and only a "
                f"failed or exhausted record can be filtered. `{listed}` lists those."
            )
        return None

    @staticmethod
    def _readers_of(backend, action: str) -> list[str]:
        """Every action below *action* in the stored dependency graph, however far."""
        found: list[str] = []
        frontier = [action]
        while frontier:
            for reader in _actions_below(backend, frontier.pop()):
                if reader not in found and reader != action:
                    found.append(reader)
                    frontier.append(reader)
        return found

    @staticmethod
    def _drop_tombstones(backend, action: str, record_id: str) -> int:
        """Take *record_id*'s tombstones out of *action*'s output, returning how many."""
        dropped = 0
        for relative_path in backend.list_target_files(action):
            rows = backend.read_target_for_rewrite(action, relative_path)
            kept = [
                row
                for row in rows
                if not (row.get("source_guid") == record_id and row.get("_tombstone"))
            ]
            if len(kept) != len(rows):
                backend.write_target(action, relative_path, kept)
                dropped += len(rows) - len(kept)
        return dropped

    @staticmethod
    def _filter_the_manifest(
        manifest_file: Path,
        manifest: dict[str, Any],
        rows: list[DispositionRow],
        below: dict[str, list[str]],
    ) -> bool:
        filtered = {
            (action, record_id): {
                "action_name": action,
                "record_id": record_id,
                "disposition": disposition,
                "reason": reason,
                "relative_path": relative_path,
                "detail": detail,
            }
            for action, record_id, disposition, reason, relative_path, _, detail in rows
        }
        cascaded = {
            (reader, record_id) for action, record_id in filtered for reader in below[action]
        }
        kept: list[dict] = []
        for row in manifest.get("dispositions", []):
            key = (row.get("action_name"), row.get("record_id"))
            if key in filtered:
                kept.append(filtered[key])
            elif not (key in cascaded and row.get("disposition") == DISPOSITION_UNPROCESSED):
                kept.append(row)
        if kept == manifest.get("dispositions", []):
            return False
        atomic_json_write(manifest_file, {**manifest, "dispositions": kept}, indent=2)
        return True

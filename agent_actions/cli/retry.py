"""Retry command for the Agent Actions CLI.

Retries failed/exhausted records from a specific action forward.
Uses the disposition table to identify what failed and delegates to
the existing workflow execution engine for re-processing.
"""

import datetime
import json
import logging
import traceback
from collections.abc import Container, Sequence
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.logging.factory import LoggerFactory
from agent_actions.processing.disposition_gate import (
    answered_by_repair,
    found_by_repair,
    note_cleared_by_repair,
)
from agent_actions.processing.repair_lineage import keep_notes_at, notes_kept_at, resume_notes
from agent_actions.record.reasons import BATCH_ABANDONED, HALTED_ON_EXHAUSTED
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_SKIPPED,
    FAILURE_DISPOSITIONS,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.tooling.docs.run_tracker import RunTracker
from agent_actions.utils.atomic_write import atomic_json_write

logger = logging.getLogger(__name__)

_RETRY_MANIFEST_NAME = "_retry_manifest.json"
# What the retry the manifest names noted below each split it re-ran (repair_lineage).
_REPAIR_NOTES_NAME = "_retry_repair_notes.json"


def _manifest_path(store_dir: Path) -> Path:
    """Return the retry manifest file path within the workflow store directory."""
    return store_dir / _RETRY_MANIFEST_NAME


def _notes_path(manifest_file: Path) -> Path:
    return manifest_file.with_name(_REPAIR_NOTES_NAME)


def _write_manifest(
    path: Path,
    from_action: str,
    record_ids: list[str],
    downstream_actions: list[str],
    dispositions: list[dict],
    *,
    put_back_from: str | None = None,
) -> str:
    """Write a retry manifest before clearing dispositions, returning its ``created_at``.

    ``put_back_from`` is the ``created_at`` of the manifest a finished re-run narrows to
    what it puts back. It is kept, since the actions that retry left are stamped with it.
    """
    created_at = put_back_from or datetime.datetime.now(datetime.UTC).isoformat()
    manifest: dict[str, Any] = {
        "from_action": from_action,
        "record_ids": sorted(record_ids),
        "downstream_actions": downstream_actions,
        "dispositions": dispositions,
        "created_at": created_at,
    }
    if put_back_from:
        manifest["put_back"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, manifest, indent=2)
    return created_at


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


def _classify_outcome(state_mgr: Any) -> str:
    """Decide the finished workflow the way ``run.py`` decides it.

    Both commands hand this status to the run tracker and turn it into an exit
    code, so a caller reading one reads the other. An action that completed with
    record-level failures is a complete action, and so a success.
    """
    if state_mgr.is_workflow_complete():
        return "SUCCESS"
    if not state_mgr.is_workflow_done():
        return "PAUSED"
    return "FAILED" if state_mgr.has_any_failed() else "SUCCESS"


def _halted_among(failures: dict[str, list[dict]], actions: list[str]) -> list[str]:
    """The *actions* halted by ``on_exhausted: raise``, in order.

    Read from the failures the retry plans over, not from the store, so a dry run sees
    the halt an interrupted retry's snapshot would put back.
    """
    return [
        action
        for action in actions
        if any(
            row.get("record_id") == NODE_LEVEL_RECORD_ID
            and row.get("detail") == HALTED_ON_EXHAUSTED
            for row in failures.get(action, [])
        )
    ]


def _delete_manifest(path: Path) -> None:
    """Delete the retry manifest and its repair notes once the re-run has reached the end,
    failed or not."""
    for kept in (path, _notes_path(path)):
        try:
            kept.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Could not delete retry manifest %s: %s", kept, e)


class RetryCommand:
    """Retry failed/exhausted records from a given action forward."""

    def __init__(self, args: RetryCommandArgs):
        self.args = args
        self.agent_name = Path(args.agent).stem
        self.console = Console()
        self._abandoned: set[tuple[str, str, str]] = set()

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

        # read_only in BOTH modes: _find_failures below reads the disposition
        # rows the startup reset would have cleared, and the non-dry-run path
        # makes its own status transitions once it knows what to retry.
        workflow = load_workflow(self.agent_name, paths, project_root, read_only=True)
        execution_order = list(workflow.execution_order)
        state_mgr = workflow.services.core.state_manager

        resumed = self._left_by_an_interrupted_retry(prior_manifest, state_mgr)
        restoring = self._snapshot_to_restore(prior_manifest, resumed, state_mgr)
        # Read before the restore deletes them with the manifest.
        notes_to_resume = notes_kept_at(
            _notes_path(manifest_file), (prior_manifest or {}).get("created_at")
        )
        never_run_since = self._not_run_since_an_interrupted_retry(resumed, state_mgr)
        if self._refused_below_a_stopped_retry(
            prior_manifest, bool(restoring or never_run_since), execution_order
        ):
            return
        if prior_manifest and self.args.dry_run:
            self.console.print(
                "[yellow]Found incomplete retry manifest — prior retry was interrupted. "
                f"A retry would restore {len(restoring)} disposition(s) first, and this "
                "plan counts them.[/yellow]"
            )
        elif prior_manifest:
            self.console.print(
                "[yellow]Found incomplete retry manifest — "
                "prior retry was interrupted. Restoring dispositions...[/yellow]"
            )
            for row in restoring:
                backend.set_disposition(
                    row["action_name"],
                    row["record_id"],
                    row["disposition"],
                    reason=row.get("reason"),
                    relative_path=row.get("relative_path"),
                    detail=row.get("detail"),
                    input_snapshot=row.get("input_snapshot"),
                )
            # The manifest and its notes stay until this retry writes its own: one that
            # stops short of that leaves the stopped retry for the next to resume.
            self.console.print(
                f"[cyan]Restored {len(restoring)} disposition(s). Proceeding with retry.[/cyan]"
            )

        unwritten = restoring if self.args.dry_run else []
        unwritten = unwritten + self._settle_lost_dispositions(
            backend, state_mgr, execution_order, resumed
        )
        failures = self._find_failures(backend, execution_order, unwritten)

        if not failures:
            found = self._failures_when_none_is_recorded(
                backend, state_mgr, execution_order, unwritten
            )
            if found is None:
                return
            if not found:
                self.console.print(
                    "[green]No failed or exhausted records found. Nothing to retry.[/green]"
                )
                return
            failures = found

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

        from_idx = execution_order.index(from_action)
        downstream_actions = execution_order[from_idx:]
        record_ids = {r["record_id"] for r in target_records}
        repairing = self._records_this_repair_may_process(record_ids, downstream_actions, failures)
        owed = self._batches_owed(backend, downstream_actions)

        # Above the dry-run return as well as the manifest: a refusal costs nothing
        # here, and a dry run that withheld it would describe a retry that is not
        # going to happen. Unfinished actions first, since abandoning a batch writes.
        # Every action, not only the range: the run executes whatever is not complete.
        if repairing:
            holding = {action for action, *_ in owed}
            readers = workflow.services.core.action_executor.readers_of
            self._refuse_to_narrow_the_unfinished(
                state_mgr,
                backend,
                [a for a in execution_order if a not in resumed],
                halted=_halted_among(failures, downstream_actions),
                holding_a_batch=holding,
                reading_a_batch={reader for action in holding for reader in readers(action)},
            )
        elif _halted_among(failures, [from_action]):
            self.console.print(
                f"\n[cyan]{from_action} is halted by on_exhausted: raise, so this retry "
                f"resumes it in full: it and the actions after it run on every record they "
                f"hold no stored answer for, not only those listed. What it answered in the "
                f"file it halted in was never stored, so it is asked again.[/cyan]"
            )
        self._settle_batches_in_flight(backend, owed)

        if self.args.dry_run:
            self.console.print("\n[yellow]Dry run — no changes made.[/yellow]")
            return

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
        created_at = _write_manifest(
            manifest_file,
            from_action,
            list(record_ids),
            downstream_actions,
            snapshot_dispositions,
        )

        workflow.set_retried_records(repairing)
        runner_backend = workflow.services.core.action_runner.storage_backend
        note_cleared_by_repair(runner_backend, record_ids - {NODE_LEVEL_RECORD_ID})
        resume_notes(runner_backend, notes_to_resume, never_run_since)
        keep_notes_at(runner_backend, _notes_path(manifest_file), created_at)

        cleared = self._clear_for_the_rerun(backend, downstream_actions, record_ids, repairing)

        self.console.print(
            f"\n[cyan]Cleared {cleared} disposition(s) for "
            f"{len(record_ids - {NODE_LEVEL_RECORD_ID})} record(s) "
            f"across {len(downstream_actions)} action(s).[/cyan]"
        )

        self.console.print("\n[bold]Re-running workflow...[/bold]\n")

        # Reset action-level status for downstream actions to PENDING so the
        # coordinator doesn't skip them as "already completed." Stamped, so a retry
        # resuming this one after an interrupt knows which it left that way.
        # Deferred import: avoid circular import at module load time.
        from agent_actions.workflow.managers.state import REPAIRED_BY, ActionStatus

        for action in downstream_actions:
            state_mgr.update_status(action, ActionStatus.PENDING, **{REPAIRED_BY: created_at})

        tracker = RunTracker(project_root=project_root)
        run_id = tracker.start_workflow_run(
            workflow_id=self.agent_name,
            workflow_name=self.agent_name,
            actions_total=len(workflow.execution_order),
        )
        workflow.services.core.action_executor.run_tracker = tracker
        workflow.services.core.action_executor.run_id = run_id
        from agent_actions.prompt.context.scope_application import build_workflow_metadata

        workflow.services.core.action_runner.workflow_metadata = build_workflow_metadata(
            name=self.agent_name, run_id=run_id
        )

        agent_folder = workflow.services.core.action_runner.get_action_folder(self.agent_name)
        LoggerFactory.initialize(
            output_dir=agent_folder,
            workflow_name=self.agent_name,
            invocation_id=run_id,
            force=True,
        )

        status = "FAILED"
        error_message = None
        try:
            workflow.run()
            self._put_back_what_the_repair_never_answered(
                backend,
                workflow,
                manifest_file,
                created_at,
                from_action,
                downstream_actions,
                record_ids,
                snapshot_dispositions,
                halted_above=_halted_among(failures, execution_order[:from_idx]),
            )
            status = _classify_outcome(state_mgr)
        except Exception:
            error_message = traceback.format_exc()
            raise
        finally:
            try:
                tracker.finalize_workflow_run(
                    run_id=run_id, status=status, error_message=error_message
                )
            except Exception as track_error:
                logger.warning(
                    "Could not finalize retry run tracking: %s",
                    track_error,
                    exc_info=True,
                )

            try:
                LoggerFactory.flush()
            except Exception as e:
                logger.debug("Failed to flush event handlers: %s", e, exc_info=True)

        # The repair ran to the end, so the dispositions on disk are the current
        # truth whatever the outcome; replaying the snapshot over them would
        # reinstate the failures this run just re-decided.
        _delete_manifest(manifest_file)

        if status == "FAILED":
            self._report_failures(state_mgr, list(workflow.execution_order))
            raise SystemExit(1)

        self.console.print("\n[green]Retry complete.[/green]")

    @staticmethod
    def _clear_for_the_rerun(
        backend, downstream_actions: list[str], record_ids: set[str], repairing: set[str]
    ) -> int:
        """Forget, at each action the retry runs, what it is asked to decide again.

        The checkpoint rows cleared are those of the records whose dispositions are: a
        record keeping its `success` keeps the row that says it was answered after its
        stored file, or that is its only answer where none was stored. Clearing it carried
        the stored row an edit had replaced, or asked the record again.
        """
        cleared = 0
        forgetting = (record_ids | repairing) - {NODE_LEVEL_RECORD_ID}
        for action in downstream_actions:
            for record_id in record_ids:
                cleared += backend.clear_disposition(action, record_id=record_id)
            # Clear node-level disposition so the executor doesn't see a
            # stale action-level FAILED/SKIPPED signal.
            backend.clear_disposition(action, record_id=NODE_LEVEL_RECORD_ID)
            backend.clear_checkpoint_records(action, source_guids=forgetting)
            # A registry entry not yet collected hands this repair the prior batch id
            # instead of its own narrowed submission, and the collecting run replays
            # that batch whole.
            backend.clear_batch_state(action)
        return cleared

    def _put_back_what_the_repair_never_answered(
        self,
        backend,
        workflow,
        manifest_file: Path,
        created_at: str,
        from_action: str,
        downstream_actions: list[str],
        cleared_ids: set[str],
        cleared_rows: list[dict],
        halted_above: list[str] = (),  # type: ignore[assignment]
    ) -> None:
        """Put back what was cleared for a record the re-run never answered at *from_action*.

        A repair selects records by the source_guid they arrive with, so a failure under
        an id no input carries — an earlier release's batch target_id, one set by hand, a
        record whose input is gone — is cleared and never re-decided, as is one in a file
        that failed or at an action that did not finish. Left cleared, it is forgotten and
        the action reads complete over the row it still holds. Each action gets its rows
        for such a record back unless it answered or decided the record itself: a file
        that fails after writing its records' dispositions has decided them.
        """
        runner_backend = workflow.services.core.action_runner.storage_backend

        def settled(action: str) -> set[str]:
            decided = {row["record_id"] for row in backend.get_disposition(action)}
            return decided | answered_by_repair(runner_backend, action)

        never_answered = cleared_ids - settled(from_action) - {NODE_LEVEL_RECORD_ID}
        if not never_answered:
            return
        put_back: list[dict] = []
        for action in downstream_actions:
            unsettled = never_answered - settled(action)
            put_back.extend(
                row
                for row in cleared_rows
                if row["action_name"] == action and row["record_id"] in unsettled
            )
        # From here an interruption restores these rows, and nothing the re-run decided.
        _write_manifest(
            manifest_file,
            from_action,
            list(never_answered),
            downstream_actions,
            put_back,
            put_back_from=created_at,
        )
        backend.set_dispositions_batch(
            [
                (
                    row["action_name"],
                    row["record_id"],
                    row["disposition"],
                    row.get("reason"),
                    row.get("relative_path"),
                    row.get("input_snapshot"),
                    row.get("detail"),
                )
                for row in put_back
            ]
        )

        # Deferred import: avoid circular import at module load time.
        from agent_actions.workflow.managers.state import ActionStatus

        state_mgr = workflow.services.core.state_manager
        ran_to_the_end = state_mgr.get_status(from_action) in {
            ActionStatus.COMPLETED,
            ActionStatus.COMPLETED_WITH_FAILURES,
            ActionStatus.SKIPPED,
            ActionStatus.BATCH_SUBMITTED,
        }
        for action in dict.fromkeys(row["action_name"] for row in put_back):
            # The run read the action complete without these; read it again as the
            # executor does, so it does not stay complete over the failures it holds.
            if state_mgr.get_status(action) == ActionStatus.COMPLETED and backend.get_failed_items(
                action
            ):
                state_mgr.update_status(
                    action,
                    ActionStatus.COMPLETED_WITH_FAILURES
                    if backend.has_successful_items(action)
                    else ActionStatus.FAILED,
                )

        if not ran_to_the_end:
            self._say_unrepaired(
                from_action,
                never_answered,
                f"were not repaired, because '{from_action}' did not finish, and their "
                f"failures stand",
                "Fix what stopped it and run retry again.",
            )
            return
        readers = workflow.services.core.action_executor.readers_of
        halted = [h for h in halted_above if from_action in readers(h)]
        if state_mgr.get_status(from_action) == ActionStatus.SKIPPED and halted:
            named = ", ".join(f"'{h}'" for h in halted)
            self._say_unrepaired(
                from_action,
                never_answered,
                f"were not repaired, because '{from_action}' was skipped: {named} is halted "
                f"by on_exhausted: raise, and a halted action is not re-run, so their "
                f"failures stand",
                f"Resume the halt with `agac retry --from {halted[0]}`, which runs "
                f"'{from_action}' again on every record it holds no stored answer for.",
            )
            return
        found = found_by_repair(runner_backend, from_action)
        self._say_unrepaired(
            from_action,
            never_answered & found,
            f"were in a file '{from_action}' failed to process, so nothing repaired them "
            f"and their failures stand",
            "The run log names the error: fix it and run retry again.",
        )
        self._say_unrepaired(
            from_action,
            never_answered - found,
            "were not in its input, so nothing repaired them and their failures stand",
            "Retry selects a record by the source_guid it arrives with. Where a record's "
            "input is gone, restore it as it was; an id no input carries, such as a target "
            "id an earlier release recorded or one set by hand, is cleared only by starting "
            "over with `agac run --fresh`.",
        )

    def _say_unrepaired(self, action: str, record_ids: set[str], what: str, remedy: str) -> None:
        if not record_ids:
            return
        named = sorted(record_ids)
        listing = ", ".join(named[:10]) + (
            f" and {len(named) - 10} more" if len(named) > 10 else ""
        )
        self.console.print(
            f"\n[yellow]{len(named)} record(s) named at '{action}' {what}: {listing}. "
            f"{remedy}[/yellow]"
        )

    def _report_failures(self, state_mgr, execution_order: list[str]) -> None:
        failed = state_mgr.get_failed_actions(execution_order)
        skipped = state_mgr.get_skipped_actions(execution_order)
        self.console.print(f"\n[red]Retry finished with failures for: {self.agent_name}[/red]")
        self.console.print(f"  Failed actions: {', '.join(failed)}")
        if skipped:
            self.console.print(f"  Skipped actions: {', '.join(skipped)}")

    def _settle_lost_dispositions(
        self, backend, state_mgr, execution_order: list[str], resumed: set[str]
    ) -> list[dict]:
        """Write the dispositions a collect pass stored rows for but could not record.

        Those records kept ``deferred``, which no retry starts from, so a failure among
        them would never be found (``lost_dispositions``). Only completed actions hold
        them; nothing is submitted again. A dry run writes nothing and returns them, to be
        planned over as written.
        """
        from agent_actions.workflow.managers.batch import (
            lost_dispositions,
            settle_lost_dispositions,
        )
        from agent_actions.workflow.managers.state import COMPLETED_STATUSES, ActionStatus

        unwritten: list[dict] = []
        for action in execution_order:
            if action in resumed or state_mgr.get_status(action) not in COMPLETED_STATUSES:
                continue
            settled = lost_dispositions(backend, action)
            outcomes = [row for row in settled if row[2] != DISPOSITION_DEFERRED]
            if not settled:
                continue
            if self.args.dry_run:
                unwritten.extend(
                    {
                        "action_name": row[0],
                        "record_id": row[1],
                        "disposition": row[2],
                        "reason": row[3],
                        "detail": row[6],
                    }
                    for row in outcomes
                )
                self.console.print(
                    f"[yellow]{action} holds {len(settled)} record(s) still deferred after "
                    f"its batch was collected. A retry writes the disposition their stored "
                    f"rows stand for first, and this plan counts them.[/yellow]"
                )
                continue
            settle_lost_dispositions(backend, settled)
            self.console.print(
                f"[cyan]{action}: wrote the disposition of {len(settled)} record(s) left "
                f"deferred after its batch was collected, from their stored rows.[/cyan]"
            )
            if any(row[2] in FAILURE_DISPOSITIONS for row in outcomes) and (
                state_mgr.get_status(action) == ActionStatus.COMPLETED
            ):
                state_mgr.update_status(action, ActionStatus.COMPLETED_WITH_FAILURES)
        return unwritten

    def _refused_below_a_stopped_retry(
        self, manifest: dict[str, Any] | None, unfinished: bool, execution_order: list[str]
    ) -> bool:
        """Refuse a ``--from`` below where a stopped retry, still to be resumed, started.

        The retry resuming it starts where it did, from the failures it puts back, and a
        retry starting below never reaches them, so it would leave the stopped one's
        records unanswered below what it re-ran. Refused before anything is put back.
        True when a dry run has reported the refusal instead.
        """
        from_action = self.args.from_action
        started = (manifest or {}).get("from_action")
        if not (from_action and started and unfinished):
            return False
        if from_action not in execution_order or started not in execution_order:
            return False
        if execution_order.index(from_action) <= execution_order.index(started):
            return False
        reason = (
            f"A retry from {started} was stopped before it finished, and a retry from "
            f"{from_action} starts below it, so it would not answer what that one named. "
            f"Resume it first — agac retry -a {self.agent_name} — then retry from "
            f"{from_action} if anything is still failed there."
        )
        if self.args.dry_run:
            self.console.print(f"\n[yellow]This retry would be refused: {reason}[/yellow]")
            return True
        raise click.ClickException(reason)

    @staticmethod
    def _left_by_an_interrupted_retry(manifest: dict[str, Any] | None, state_mgr) -> set[str]:
        """What an interrupted retry put back to pending and nothing has reset since.

        Read from the stamp that retry left beside each status, not from its manifest
        alone: only a retry reads or deletes the manifest, so it outlives any number of
        plain runs, and a reset by one of them leaves the action as unfinished as any.
        """
        from agent_actions.workflow.managers.state import REPAIRED_BY

        if not manifest or not manifest.get("created_at"):
            return set()
        return {
            action
            for action in manifest.get("downstream_actions", [])
            if state_mgr.get_status_details(action).get(REPAIRED_BY) == manifest["created_at"]
        }

    @staticmethod
    def _not_run_since_an_interrupted_retry(resumed: set[str], state_mgr) -> set[str]:
        """The actions an interrupted retry put back to pending and never completed.

        What that retry noted for them below a split it re-ran is still to be taken out
        of them: a retry resuming it re-runs the split over the rows that one wrote, and
        sees only those taken away.
        """
        from agent_actions.workflow.managers.state import COMPLETED_STATUSES

        return {
            action for action in resumed if state_mgr.get_status(action) not in COMPLETED_STATUSES
        }

    @staticmethod
    def _snapshot_to_restore(
        manifest: dict[str, Any] | None, resumed: set[str], state_mgr
    ) -> list[dict]:
        """The rows of an interrupted retry's snapshot that go back before this one plans.

        None once every action that retry put back to pending has completed: what they
        hold is newer. Otherwise those actions' rows, the completed ones' included, since
        the next retry starts where that one did, from its starting action's failures;
        the readers hold what they had not answered as ``unprocessed``, which no retry
        starts from. An action a reset has touched since holds newer rows and gets none.
        Nor does a completed action get a node-level failure back, which a plain run
        would take as a reason to run it again over what its readers hold. A manifest the
        finished re-run narrowed to what it puts back (``put_back``) goes back even where
        every action completed: it holds only records that re-run did not decide again.
        """
        from agent_actions.workflow.managers.state import COMPLETED_STATUSES

        completed = {
            action for action in resumed if state_mgr.get_status(action) in COMPLETED_STATUSES
        }
        if not manifest or (completed == resumed and not manifest.get("put_back")):
            return []
        return [
            row
            for row in manifest.get("dispositions", [])
            if row["action_name"] in resumed
            and not (row["record_id"] == NODE_LEVEL_RECORD_ID and row["action_name"] in completed)
        ]

    def _refuse_to_narrow_the_unfinished(
        self,
        state_mgr,
        backend,
        actions: list[str],
        *,
        halted: Sequence[str] = (),
        holding_a_batch: Container[str] = (),
        reading_a_batch: Container[str] = (),
    ) -> None:
        """Refuse a repair that would narrow an action holding no answer for some record.

        A repair carries what each action holds for the records it does not name. An
        action never run since it was put back to pending, stopped partway through its
        records, or whose output is gone has answered none of the ones it had not
        reached, so narrowing it completes it without them and nothing runs it again.
        A plain run finishes it. Nor has one *halted* by ``on_exhausted: raise``, which
        the repair would clear, answered the records past the halt. A plain run will not
        resume it; a retry from it, which names no record, runs it in full.

        Callers leave out what an interrupted retry put back to pending: it had
        finished before that retry, and retrying again resumes it. Not refused either:
        a failure that reached all of the action's input, which the repair is for, and
        a halt the repair does not clear, which stays halted. An action holding a batch
        nobody has collected, or reading one that does, is left to that batch's own
        refusal, which ``--abandon-in-flight`` is the way past.
        """
        from agent_actions.workflow.managers.state import COMPLETED_STATUSES, ActionStatus

        # What a collect pass leaves: stopped, failed, or, in an earlier version, completed
        # past a file it skipped.
        # A run stopped while submitting cannot be told from one stopped collecting.
        left_by_collecting = {ActionStatus.CHECKING_BATCH, ActionStatus.FAILED, *COMPLETED_STATUSES}
        unfinished = [f"{action} (halted)" for action in halted]
        for action in actions:
            if action in halted:
                continue
            status = state_mgr.get_status(action)
            if action in reading_a_batch or (
                action in holding_a_batch and status in left_by_collecting
            ):
                continue
            label = self._unfinished_as(backend, action, status)
            if label:
                unfinished.append(f"{action} ({label})")
        if not unfinished:
            return

        remedy = f"Run the workflow first — agac run -a {self.agent_name} — then retry."
        if halted:
            resume = (
                f"resume {halted[0]} with a retry from it, which names no record and runs it "
                f"in full — agac retry -a {self.agent_name} --from {halted[0]} — then retry."
            )
            remedy = (
                f"Run the workflow first — agac run -a {self.agent_name} — then {resume}"
                if len(unfinished) > len(halted)
                else f"First {resume}"
            )
        reason = (
            f"{len(unfinished)} action(s) hold no current answer for some of their records "
            f"({', '.join(unfinished)}). A retry answers only the records it names and "
            f"carries what each action holds for the rest, so it would complete them "
            f"without those answers. {remedy}"
        )
        if self.args.dry_run:
            self.console.print(f"\n[yellow]This retry would be refused: {reason}[/yellow]")
            return
        raise click.ClickException(reason)

    @classmethod
    def _unfinished_as(cls, backend, action: str, status) -> str | None:
        """How *action* is left without an answer for some record, or None if it is not."""
        from agent_actions.workflow.executor import (
            action_failed_every_input,
            action_is_halted,
            completed_output_stands,
        )
        from agent_actions.workflow.managers.state import (
            COMPLETED_STATUSES,
            MID_PROCESSING_STATUSES,
            ActionStatus,
        )

        if status in COMPLETED_STATUSES:
            return None if completed_output_stands(backend, action) else "its output is gone"
        if status in MID_PROCESSING_STATUSES or status == ActionStatus.PENDING:
            return ActionStatus(status).value
        # A halt is refused only where the repair clears it, which the caller decides.
        if status != ActionStatus.FAILED or action_is_halted(backend, action):
            return None
        reached_all = action_failed_every_input(backend, action) or cls._batches_answer_all_sent(
            backend, action
        )
        if reached_all and not cls._holds_rows_its_failure_did_not_reach(backend, action):
            return None
        return ActionStatus.FAILED.value

    @classmethod
    def _batches_answer_all_sent(cls, backend, action: str) -> bool:
        """Whether a batch action holds an answer or a failure for every record it sent.

        Its batches were sent all of its input, which the submission walks before any
        is collected; a collect pass that failed on a file marks that file's records
        failed and writes no node-level marker.
        """
        from agent_actions.errors import ProcessingError
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        jobs = BatchRegistryManager(backend, action).get_all_jobs()
        if not jobs:
            return False
        held = {row["record_id"]: row["disposition"] for row in backend.get_disposition(action)}
        for file_name, entry in jobs.items():
            try:
                sent = cls._records_sent(backend, action, entry.parent_file_name or file_name)
            except ProcessingError:
                return False
            if any(held.get(record_id) in (None, DISPOSITION_DEFERRED) for record_id in sent):
                return False
        return True

    @staticmethod
    def _holds_rows_its_failure_did_not_reach(backend, action: str) -> bool:
        """Whether a failed action holds a row of a record its failing run did not reach.

        A run that fails every record of a file writes it with those failures after a
        reset, keeping none of its older rows, but writes nothing for a file it failed
        before processing it, so every row there is older. The row of a record holding
        a disposition was answered since the action was last reset, or failed and is
        reached by a later retry. Any other row predates that reset — its record left
        the input, or is filtered or scoped out, keeping no row — and narrowing would
        carry it.
        """
        reached = {
            row["record_id"]
            for row in backend.get_disposition(action)
            if row.get("disposition") not in (DISPOSITION_FILTERED, DISPOSITION_SKIPPED)
        }
        return any(
            guid not in reached and parent not in reached
            for guid, parent in backend.target_row_identities(action)
        )

    def _failures_when_none_is_recorded(
        self, backend, state_mgr, execution_order: list[str], unwritten: list[dict]
    ) -> dict[str, list[dict]] | None:
        """What a retry finds when no failed record is recorded: a refusal, or nothing.

        A collect pass that stopped on an error leaves its action failed and the
        batch it could not read still owed, which is not nothing to retry. Stores
        written before the executor recorded that failure hold it with no row. An
        action that is not failed has nothing to retry, whatever batch it waits on.
        Abandoning the batch strands its waiting records as failed, and those are
        then the failures. None when a dry run has already reported the refusal.

        A failed action owing no batch failed as a whole where the store could not
        record it, as when the store errs before the action's work begins: its
        failure is the action's own, and the retry re-runs it in full.
        """
        failed = state_mgr.get_failed_actions(execution_order)
        if not failed:
            return {}
        owed = self._batches_owed(backend, failed)
        if not owed:
            return self._record_failures_of_the_actions(backend, state_mgr, failed)
        self._settle_batches_in_flight(backend, owed)
        if self.args.dry_run:
            return None
        return self._find_failures(backend, execution_order, unwritten)

    def _record_failures_of_the_actions(
        self, backend, state_mgr, failed: list[str]
    ) -> dict[str, list[dict]]:
        """Give each failed action the node-level failure its run could not store.

        That row is what an action failing in its own handler stores, so the retry
        plans, snapshots and clears it as it does that one. Its reason is the error
        in the action's status. A dry run writes nothing and plans over the rows.
        """
        failures: dict[str, list[dict]] = {}
        for action in failed:
            reason = state_mgr.get_status_details(action).get("error_message") or (
                "the action failed before any of its records held a failure"
            )
            if not self.args.dry_run:
                backend.set_disposition(
                    action, NODE_LEVEL_RECORD_ID, DISPOSITION_FAILED, reason=reason
                )
            failures[action] = [
                {
                    "action_name": action,
                    "record_id": NODE_LEVEL_RECORD_ID,
                    "disposition": DISPOSITION_FAILED,
                    "reason": reason,
                }
            ]
        if self.args.dry_run:
            return failures
        return self._find_failures(backend, failed)

    def _batches_owed(self, backend, actions: list[str]) -> list[tuple[str, str, str, str]]:
        """Every batch nobody has collected that this repair would lose, as
        (action, batch_id, file_name, state).

        It owns the records it was submitted for. That holds for a batch that has
        finished and not been collected as much as for one still out: the repair
        clears the registry entry, which is all that names it. Whether such a batch
        is still owed is asked of its records, not of the entry or the action: an
        entry written before ``collected_at`` existed has no stamp either, and an
        earlier version could complete an action past a file it skipped.
        """
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        owed: list[tuple[str, str, str, str]] = []
        for action in actions:
            for file_name, entry in BatchRegistryManager(backend, action).get_all_jobs().items():
                if entry.is_in_flight:
                    owed.append((action, entry.batch_id, file_name, "in flight"))
                elif entry.awaits_collection and self._records_waiting_on(
                    backend, [(action, entry.batch_id, file_name, "")]
                ):
                    owed.append((action, entry.batch_id, file_name, "finished, not collected"))
        return owed

    def _settle_batches_in_flight(self, backend, owed: list[tuple[str, str, str, str]]) -> None:
        """Decide what the batches this repair would lose (``_batches_owed``) mean for it.

        A repair starting on top of one submits a second batch over the same file, and
        whichever is collected last wins while the other is paid for and discarded —
        so by default this refuses, before anything is cleared.

        Two exceptions. A dry run reports the refusal instead of raising: it is
        the documented way to see what a retry would do, and it changes nothing
        either way. And ``--abandon-in-flight`` proceeds, because every remedy the
        refusal names needs the provider to answer about the batch, which it
        cannot when it has forgotten the id.
        """
        # Finding the failures may already have abandoned these, and an abandoned
        # batch stays in the registry until the retry clears it.
        owed = [o for o in owed if o[:3] not in self._abandoned]
        if not owed:
            return

        listing = ", ".join(
            f"{batch_id} ({action}, {state})" for action, batch_id, _, state in sorted(owed)
        )
        remedy = (
            "Collect them first — run the workflow again — then retry. "
            "If the provider no longer has them, pass --abandon-in-flight."
        )

        # Dry run first, and before anything is written: abandoning strands records,
        # and a dry run that did that would be writing to the store under the one
        # flag documented to change nothing.
        if self.args.dry_run:
            if self.args.abandon_in_flight:
                waiting = self._records_waiting_on(backend, owed)
                self.console.print(
                    f"\n[yellow]This retry would abandon {len(owed)} batch job(s) "
                    f"not collected yet ({listing}), giving up whatever they return, and "
                    f"would mark {len(waiting)} record(s) waiting on them failed so a "
                    f"later retry can still reach them.[/yellow]"
                )
            else:
                self.console.print(
                    f"\n[yellow]This retry would be refused: {len(owed)} batch job(s) "
                    f"not collected yet ({listing}). {remedy}[/yellow]"
                )
            return

        if self.args.abandon_in_flight:
            waiting = self._records_waiting_on(backend, owed)
            stranded = self._strand_deferred_records(backend, waiting)
            self._abandoned.update(o[:3] for o in owed)
            self.console.print(
                f"\n[yellow]Abandoning {len(owed)} batch job(s) not collected yet: "
                f"{listing}. Whatever they return will not be collected. "
                f"{stranded} record(s) waiting on them are marked failed so a later "
                f"retry can still reach them.[/yellow]"
            )
            return

        raise click.ClickException(
            f"{len(owed)} batch job(s) not collected yet ({listing}). Their results would "
            f"be lost to this repair's own submission. {remedy}"
        )

    @classmethod
    def _records_waiting_on(
        cls, backend, owed: list[tuple[str, str, str, str]]
    ) -> list[tuple[str, str]]:
        """Every record these batches hold that nothing has answered, as (action, record_id).

        Read from each batch's own context map, which lists what it was sent. A record
        is waiting while its disposition says ``deferred``, and also when it has none:
        a run's reset clears ``deferred``, and finding the batch again does not put it
        back. A stored row says nothing either way, since a batch sent to repair a
        record finds that record's old row still there.

        Read-only, so the dry run can report what abandoning would cost without
        paying it.
        """
        from agent_actions.errors import ProcessingError
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        waiting: set[tuple[str, str]] = set()
        for action in sorted({action for action, *_ in owed}):
            dispositions = {
                row["record_id"]: row["disposition"] for row in backend.get_disposition(action)
            }
            jobs = BatchRegistryManager(backend, action).get_all_jobs()
            for owed_action, batch_id, file_name, _state in owed:
                if owed_action != action:
                    continue
                # A recovery round is registered under its own name and sent from the
                # map of the file it recovers.
                entry = jobs.get(file_name)
                sent_as = (entry.parent_file_name if entry else None) or file_name
                try:
                    sent = cls._records_sent(backend, action, sent_as)
                except ProcessingError as e:
                    logger.warning(
                        "Batch %s (%s) has no readable record of what it was sent, so every "
                        "deferred record of the action is taken as waiting on it: %s",
                        batch_id,
                        action,
                        e,
                    )
                    waiting.update(cls._deferred_record_ids(backend, {action}))
                    continue
                for record_id in sent:
                    held = dispositions.get(record_id)
                    if held is None or held == DISPOSITION_DEFERRED:
                        waiting.add((action, record_id))
        return sorted(waiting)

    @staticmethod
    def _records_sent(backend, action: str, sent_as: str) -> list[str]:
        """The records a batch of *action* was sent, read from the context map of *sent_as*.

        A record sent without a ``source_guid`` is left out: collection refuses it and
        records nothing for it, and marked under its custom_id it would be a failure a
        later retry clears and cannot select.

        Raises ``ProcessingError`` when that map cannot be read.
        """
        from agent_actions.llm.batch.core.batch_constants import FilterStatus
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager

        context_map = BatchContextManager.load_batch_context_map(backend, action, sent_as)
        return [
            sent["source_guid"]
            for sent in context_map.values()
            if BatchContextMetadata.get_filter_status(sent) == FilterStatus.INCLUDED
            and sent.get("source_guid")
        ]

    @staticmethod
    def _deferred_record_ids(backend, actions: set[str]) -> list[tuple[str, str]]:
        """Every record with a ``deferred`` disposition at *actions*, as (action, record_id)."""
        return [
            (action, row["record_id"])
            for action in sorted(actions)
            for row in backend.get_disposition(action, disposition=DISPOSITION_DEFERRED)
            if row.get("record_id") and row.get("record_id") != NODE_LEVEL_RECORD_ID
        ]

    @staticmethod
    def _strand_deferred_records(backend, waiting: list[tuple[str, str]]) -> int:
        """Move records waiting on an abandoned batch to a disposition retry can see.

        ``deferred`` is left out of ``FAILURE_DISPOSITIONS`` because it means a
        batch is in flight that will resolve the record. Abandoning that batch
        ends the flight without ending the wait, so the record becomes invisible
        to ``agac retry`` and a no-op for ``agac run`` — reachable only by
        ``--fresh``, which is the loss this flag exists to avoid.
        """
        for action, record_id in waiting:
            backend.set_disposition(
                action,
                record_id,
                DISPOSITION_FAILED,
                reason=BATCH_ABANDONED,
                detail="the batch holding this record was abandoned by agac retry",
            )
        return len(waiting)

    def _records_this_repair_may_process(
        self,
        cleared_ids: set[str],
        downstream_actions: list[str],
        failures: dict[str, list[dict]],
    ) -> set[str]:
        """Every record this repair is entitled to re-run, at any action it re-runs.

        Wider than the set whose dispositions are cleared: clearing answers "what
        should this action forget", and only the starting action has to forget
        anything. This answers "what is this repair for", and a record that failed
        below the starting point is as much a part of it as one that failed at it.

        Naming a record with ``--record`` answers it outright — that record and no
        other, however many else failed.

        Empty when the only failures are node-level: that sentinel is a signal about
        an action, not a record, and a selection holding nothing else would narrow
        every real record out of the run it is supposed to repair. Empty too when the
        repair starts at an action halted by ``on_exhausted: raise`` and ``--record``
        names nothing: the halt owes every record past it, so the repair resumes it in
        full.
        """
        if self.args.record:
            repairing = set(cleared_ids)
        elif _halted_among(failures, downstream_actions[:1]):
            return set()
        else:
            repairing = set(cleared_ids)
            for action in downstream_actions:
                repairing.update(row["record_id"] for row in failures.get(action, []))
        repairing.discard(NODE_LEVEL_RECORD_ID)
        return repairing

    @staticmethod
    def _find_failures(
        backend,
        execution_order: list[str],
        unwritten: list[dict] | None = None,
    ) -> dict[str, list[dict]]:
        """Query disposition table for failed/exhausted records per action.

        *unwritten* rows are read as written, each replacing what its action holds for
        its record: a dry run plans over the snapshot it does not restore.
        """
        failures: dict[str, list[dict]] = {}
        for action in execution_order:
            replacing = {r["record_id"]: r for r in unwritten or [] if r["action_name"] == action}
            rows = [
                r for r in backend.get_disposition(action) if r.get("record_id") not in replacing
            ]
            rows.extend(replacing.values())
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

        # The __node__ row is the action's own status, not a record.
        records = [r for r in target_records if r.get("record_id") != NODE_LEVEL_RECORD_ID]
        action_rows = [r for r in target_records if r.get("record_id") == NODE_LEVEL_RECORD_ID]

        self.console.print("\n[bold]Retry Plan[/bold]")
        self.console.print(f"  From action: [cyan]{from_action}[/cyan]")
        self.console.print(f"  Actions to re-run: {' → '.join(downstream)}")
        for row in action_rows:
            reason = (row.get("reason") or "")[:120]
            self.console.print(
                Text(f"  Action status: {row.get('disposition', '?')}")
                + Text(f" — {reason}" if reason else "", style="dim")
            )
        self.console.print(f"  Records to retry: {len(records)}")
        if not records:
            self.console.print(
                f"  [dim]The failure is {from_action}'s own, so the retry re-runs it "
                "without narrowing it to particular records.[/dim]"
            )
            self._note_other_failures(from_action, all_failures)
            return

        table = Table(title="Failed Records")
        table.add_column("Record ID", style="red")
        table.add_column("Disposition", style="yellow")
        table.add_column("Reason", style="dim", max_width=60)

        for record in records:
            table.add_row(
                record.get("record_id", "?"),
                record.get("disposition", "?"),
                Text((record.get("reason") or "")[:60]),
            )

        self.console.print(table)
        self._note_other_failures(from_action, all_failures)

    def _note_other_failures(self, from_action: str, all_failures: dict[str, list[dict]]) -> None:
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
@click.option(
    "--abandon-in-flight",
    is_flag=True,
    default=False,
    help="Retry even though a batch has not been collected, giving up its results.",
)
@handles_user_errors("retry")
@requires_project
def retry(
    agent: str,
    from_action: str | None,
    record: str | None,
    dry_run: bool,
    abandon_in_flight: bool,
    project_root: Path | None = None,
) -> None:
    """Retry failed/exhausted records from a specific action forward."""
    args = RetryCommandArgs(
        agent=agent,
        from_action=from_action,
        record=record,
        dry_run=dry_run,
        abandon_in_flight=abandon_in_flight,
    )
    command = RetryCommand(args)
    command.execute(project_root=project_root)

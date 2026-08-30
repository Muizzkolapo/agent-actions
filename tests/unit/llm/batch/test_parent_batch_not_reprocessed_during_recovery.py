"""Only the live batch job for a parent may be processed.

Processing a spent one restarts recovery from attempt 1 — so ``retry_attempt``
never reaches ``max_attempts`` and ``on_exhausted: raise`` never fires — or
finalizes on stale results and deletes the live attempt, discarding whatever it
recovered. The recovery child is already COMPLETED when the loop sees it, so
"live" means the latest attempt, not "still in flight".
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError, ProcessingError
from agent_actions.llm.batch.core.batch_constants import BatchStatus, RecoveryType
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services.processing import BatchProcessingService

ACTION = "summarize_page_content"
PARENT = "pages.json"
CHILD = f"{PARENT}_retry_1"


class _Metadata:
    """The slice of StorageBackend the registry actually uses, kept in a dict."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value


def _entry(
    batch_id: str, status: BatchStatus, file_name: str, *, at: str = "09:00:00", **kw
) -> BatchJobEntry:
    """``at`` is registration time — what decides which entry is live."""
    return BatchJobEntry(
        batch_id=batch_id,
        status=status,
        timestamp=f"2026-08-30T{at}+00:00" if at else "",
        provider="ollama_cloud",
        record_count=1,
        file_name=file_name,
        **kw,
    )


def _child(
    batch_id: str,
    status: BatchStatus = BatchStatus.COMPLETED,
    attempt: int = 1,
    at: str = "09:01:00",
):
    return _entry(
        batch_id,
        status,
        CHILD,
        at=at,
        parent_file_name=PARENT,
        recovery_type=RecoveryType.RETRY,
        recovery_attempt=attempt,
    )


def _registry(jobs: dict[str, BatchJobEntry]) -> BatchRegistryManager:
    backend = _Metadata()
    backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
        {name: entry.to_dict() for name, entry in jobs.items()}
    )
    return BatchRegistryManager(backend, ACTION)


def _service(manager: BatchRegistryManager) -> BatchProcessingService:
    """A service whose registry is real, so mid-loop writes really land."""
    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=lambda _: manager,
        source_handler=None,
        action_indices={},
        dependency_configs={},
        storage_backend=MagicMock(),
        workflow_name=ACTION,
    )

    def resolve(batch_id, registry_manager, *_a, **_kw):
        """The real resolver's contract: an unregistered id has no client."""
        if registry_manager.get_batch_job_by_id(batch_id) is None:
            raise ConfigurationError(f"Cannot determine client for batch_id {batch_id}")
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        return provider

    service._client_resolver.get_for_batch_id.side_effect = resolve
    return service


def _run(service, *, on_process=None) -> list[str]:
    """Drive the loop; return the batch ids it chose to process.

    Processing succeeds by default: "did anything come back" is a separate
    branch of this method and would otherwise raise over these assertions.
    """
    seen: list[str] = []

    def record(*, batch_id, **kw):
        seen.append(batch_id)
        return on_process(batch_id=batch_id, **kw) if on_process else "/out/done.json"

    with patch.object(service, "_process_single_batch_file", side_effect=record):
        service.process_all_batch_results("/out", {"kind": "llm"}, action_name=ACTION)
    return seen


class TestTheSupersededParentIsNotReprocessed:
    @pytest.mark.parametrize(
        "child_status",
        [BatchStatus.COMPLETED, BatchStatus.SUBMITTED, BatchStatus.FAILED],
    )
    def test_a_parent_with_a_recovery_child_is_skipped(self, child_status):
        """The child's status is irrelevant — the parent is spent either way.

        Its results live in the recovery state's accumulated_results. Re-reading
        them is what restarts the attempt counter, so this is the assertion the
        exhaustion bug turns on. COMPLETED is the case that occurs live.
        """
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_child_v1", child_status),
            }
        )

        seen = _run(_service(manager))

        assert "batch_parent" not in seen, "the parent was consumed when the child was submitted"

    def test_the_recovery_child_is_still_processed(self):
        """Skipping the parent must not mean skipping the whole action.

        The child is where the attempt counter advances, so losing it would
        trade an endless loop for a permanent stall.
        """
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_child_v1"),
            }
        )

        assert _run(_service(manager)) == ["batch_child_v1"]

    def test_a_parent_with_no_recovery_child_still_processes(self):
        """The skip is keyed on the parent link, not on 'is a parent'."""
        manager = _registry({PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT)})

        assert _run(_service(manager)) == ["batch_parent"]

    def test_only_the_linked_parent_is_skipped(self):
        """A second action file with no recovery of its own is untouched."""
        other = "other.json"
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_child_v1"),
                other: _entry("batch_other", BatchStatus.COMPLETED, other),
            }
        )

        seen = _run(_service(manager))

        assert "batch_other" in seen
        assert "batch_parent" not in seen


class TestTheLoopReadsTheRegistryNotItsSnapshot:
    """Processing one entry rewrites others; the snapshot goes stale mid-loop."""

    def test_a_replaced_batch_id_is_not_used_after_it_is_replaced(self):
        """Registering the next attempt evicts the previous id from the index.

        The live failure is not a wrong id being processed — it is
        ``ConfigurationError`` escaping the loop and ending the whole run.
        """
        manager = _registry(
            {
                "first.json": _entry("batch_first", BatchStatus.COMPLETED, "first.json"),
                "second.json": _entry("batch_second_v1", BatchStatus.COMPLETED, "second.json"),
            }
        )

        def replace_second(*, batch_id, **_kw):
            if batch_id == "batch_first":
                manager.save_batch_job(
                    "second.json",
                    _entry("batch_second_v2", BatchStatus.COMPLETED, "second.json"),
                )
            return "/out/done.json"

        seen = _run(_service(manager), on_process=replace_second)

        assert seen == ["batch_first", "batch_second_v2"]

    def test_an_entry_deleted_mid_loop_is_not_reprocessed(self):
        """``_cleanup_recovery_entries`` removes siblings during finalization.

        A snapshot-held entry that no longer exists has nothing left to read.
        """
        manager = _registry(
            {
                "first.json": _entry("batch_first", BatchStatus.COMPLETED, "first.json"),
                "second.json": _entry("batch_second", BatchStatus.COMPLETED, "second.json"),
            }
        )

        def remove_second(*, batch_id, **_kw):
            if batch_id == "batch_first":
                manager.remove_batch_job("second.json")
            return "/out/done.json"

        assert _run(_service(manager), on_process=remove_second) == ["batch_first"]


class TestOnlyTheLiveAttemptIsProcessed:
    """A spent attempt is still COMPLETED, so nothing stopped the loop re-reading it.

    Finalizing on a spent attempt runs ``_cleanup_recovery_entries``, which
    deletes every recovery entry for the parent — including the live one — so
    whatever that attempt recovered is thrown away.
    """

    def test_an_earlier_retry_attempt_is_skipped_for_a_later_one(self):
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_retry_1", attempt=1),
                f"{PARENT}_retry_2": _entry(
                    "batch_retry_2",
                    BatchStatus.COMPLETED,
                    f"{PARENT}_retry_2",
                    at="09:02:00",
                    parent_file_name=PARENT,
                    recovery_type=RecoveryType.RETRY,
                    recovery_attempt=2,
                ),
            }
        )

        assert _run(_service(manager)) == ["batch_retry_2"]

    def test_a_reprompt_supersedes_the_retry_it_followed(self):
        """The handoff loses a whole completed reprompt batch otherwise."""
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_retry_1", attempt=1),
                f"{PARENT}_reprompt_1": _entry(
                    "batch_reprompt_1",
                    BatchStatus.COMPLETED,
                    f"{PARENT}_reprompt_1",
                    at="09:02:00",
                    parent_file_name=PARENT,
                    recovery_type=RecoveryType.REPROMPT,
                    recovery_attempt=1,
                ),
            }
        )

        assert _run(_service(manager)) == ["batch_reprompt_1"]

    def test_registering_an_attempt_removes_the_one_it_supersedes(self):
        """Prevents new stores from reaching the state above at all."""
        from agent_actions.llm.batch.services.processing_recovery import register_recovery_batch

        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_retry_1", attempt=1),
            }
        )

        register_recovery_batch(
            manager, ("batch_retry_2", 1), PARENT, "ollama_cloud", RecoveryType.RETRY, 2
        )

        assert set(manager.get_all_jobs()) == {PARENT, f"{PARENT}_retry_2"}

    def test_registering_does_not_touch_another_parents_recovery(self):
        from agent_actions.llm.batch.services.processing_recovery import register_recovery_batch

        other = "other.json"
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_retry_1", attempt=1),
                f"{other}_retry_1": _entry(
                    "batch_other_1",
                    BatchStatus.COMPLETED,
                    f"{other}_retry_1",
                    at="09:01:00",
                    parent_file_name=other,
                    recovery_type=RecoveryType.RETRY,
                    recovery_attempt=1,
                ),
            }
        )

        register_recovery_batch(
            manager, ("batch_retry_2", 1), PARENT, "ollama_cloud", RecoveryType.RETRY, 2
        )

        assert f"{other}_retry_1" in manager.get_all_jobs()


class TestTheSkippedParentIsPreservedNotDestroyed:
    def test_the_parent_entry_survives_being_skipped(self):
        """Removing it would pass every skip assertion and lose the resume point.

        The parent's entry is what ``check_batch_submission`` reads to know the
        action has jobs at all, and what a recovery's finalization writes output
        against.
        """
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_child_v1"),
            }
        )

        _run(_service(manager))

        assert PARENT in manager.get_all_jobs()


class TestTheSingleBatchSiblingRefusesASupersededId:
    """``process_batch_results`` takes a batch_id straight from its caller.

    Handed the parent's id while a recovery is live, it re-ran the original
    batch and reset the attempt counter — the same defect, one method over.
    """

    def test_it_refuses_the_parent_once_a_recovery_exists(self):
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_child_v1"),
            }
        )
        service = _service(manager)
        service._storage_backend = MagicMock()

        with patch.object(service, "_process_single_batch_file") as delegate:
            with pytest.raises(ProcessingError, match="supersedes"):
                service.process_batch_results("batch_parent", "/out", action_name=ACTION)

        delegate.assert_not_called()

    def test_it_still_processes_a_batch_with_no_recovery(self):
        manager = _registry({PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT)})
        service = _service(manager)
        service._storage_backend = MagicMock()

        with patch.object(service, "_process_single_batch_file", return_value="/out/done.json"):
            assert service.process_batch_results("batch_parent", "/out", action_name=ACTION) == (
                "/out/done.json"
            )


class TestLiveIsDecidedByRegistrationTime:
    """Not by attempt number, and not by retry-then-reprompt phase order.

    `_process_original_batch` writes `phase=RETRY` whenever it runs, so a store
    written before a parent stopped being re-processed can hold a retry
    registered *after* a reprompt. Ranking by phase picks the older reprompt;
    ranking by attempt picks whichever happens to number higher.
    """

    def test_a_retry_registered_after_a_reprompt_wins(self):
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                f"{PARENT}_reprompt_1": _entry(
                    "batch_reprompt_1",
                    BatchStatus.COMPLETED,
                    f"{PARENT}_reprompt_1",
                    at="09:01:00",
                    parent_file_name=PARENT,
                    recovery_type=RecoveryType.REPROMPT,
                    recovery_attempt=1,
                ),
                CHILD: _child("batch_retry_1", at="09:02:00", attempt=1),
            }
        )

        assert _run(_service(manager)) == ["batch_retry_1"]

    def test_a_lower_numbered_attempt_registered_later_wins(self):
        """Attempt numbers restart at 1 whenever a fresh recovery begins."""
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                f"{PARENT}_retry_2": _entry(
                    "batch_retry_2",
                    BatchStatus.COMPLETED,
                    f"{PARENT}_retry_2",
                    at="09:01:00",
                    parent_file_name=PARENT,
                    recovery_type=RecoveryType.RETRY,
                    recovery_attempt=2,
                ),
                CHILD: _child("batch_retry_1_rerun", at="09:03:00", attempt=1),
            }
        )

        assert _run(_service(manager)) == ["batch_retry_1_rerun"]


class TestRegistryShapesThatCouldStrandWork:
    """A skip that fires on the wrong key silently drops a completed batch."""

    def test_a_recovery_whose_parent_is_gone_is_still_processed(self):
        """Only the parent is skipped, and it is not there to skip."""
        manager = _registry(
            {
                "orphan_retry_1": _entry(
                    "batch_orphan",
                    BatchStatus.COMPLETED,
                    "orphan_retry_1",
                    at="09:01:00",
                    parent_file_name="gone.json",
                    recovery_type=RecoveryType.RETRY,
                    recovery_attempt=1,
                )
            }
        )

        assert _run(_service(manager)) == ["batch_orphan"]

    def test_each_parent_is_judged_against_its_own_recoveries(self):
        manager = _registry(
            {
                "a.json": _entry("batch_a", BatchStatus.COMPLETED, "a.json"),
                "a.json_retry_1": _entry(
                    "batch_a_r1",
                    BatchStatus.COMPLETED,
                    "a.json_retry_1",
                    at="09:01:00",
                    parent_file_name="a.json",
                    recovery_type=RecoveryType.RETRY,
                    recovery_attempt=1,
                ),
                "b.json": _entry("batch_b", BatchStatus.COMPLETED, "b.json"),
                "b.json_retry_1": _entry(
                    "batch_b_r1",
                    BatchStatus.COMPLETED,
                    "b.json_retry_1",
                    at="09:01:00",
                    parent_file_name="b.json",
                    recovery_type=RecoveryType.RETRY,
                    recovery_attempt=1,
                ),
            }
        )

        assert sorted(_run(_service(manager))) == ["batch_a_r1", "batch_b_r1"]

    def test_entries_without_a_timestamp_still_pick_one_live_attempt(self):
        """Pre-dating the timestamp field must not make every attempt live."""
        manager = _registry(
            {
                PARENT: _entry("batch_parent", BatchStatus.COMPLETED, PARENT),
                CHILD: _child("batch_r1", at="", attempt=1),
                f"{PARENT}_retry_2": _entry(
                    "batch_r2",
                    BatchStatus.COMPLETED,
                    f"{PARENT}_retry_2",
                    at="",
                    parent_file_name=PARENT,
                    recovery_type=RecoveryType.RETRY,
                    recovery_attempt=2,
                ),
            }
        )

        assert _run(_service(manager)) == ["batch_r2"]

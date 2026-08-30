"""A parent batch that a recovery batch superseded must not be re-processed.

The parent stays COMPLETED forever, so every run re-reads it, starts a *second*
recovery at attempt 1 — ``retry_attempt`` never reaches ``max_attempts``, so
``on_exhausted: raise`` has nothing to fire on — and overwrites the retry entry
whose batch id the loop's own registry snapshot is still holding, which then
resolves to no client and ends the run.

Measured on qanalabs ``ql_mc_retryexh`` against ``origin/main``: five runs,
``retry_attempt`` stuck at 1 of 2, an endless resubmission cycle. The recovery
child is already COMPLETED when this loop sees it — the caller polls the
provider first — so the skip cannot depend on the child still being in flight.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError
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


def _entry(batch_id: str, status: BatchStatus, file_name: str, **kw) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=batch_id,
        status=status,
        timestamp="2026-08-30T09:00:00+00:00",
        provider="ollama_cloud",
        record_count=1,
        file_name=file_name,
        **kw,
    )


def _child(batch_id: str, status: BatchStatus = BatchStatus.COMPLETED, attempt: int = 1):
    return _entry(
        batch_id,
        status,
        CHILD,
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

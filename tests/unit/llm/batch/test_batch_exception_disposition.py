"""Tests for F4: batch exception writes FAILED dispositions for abandoned records.

When _process_single_batch_file raises a non-RuntimeError exception,
process_all_batch_results must write DISPOSITION_FAILED for every INCLUDED
record in the failed batch file's context_map, clearing any stale DEFERRED
dispositions. Records in other files must be unaffected.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import BatchJobEntry, BatchRegistryStats
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.storage.backend import DISPOSITION_FAILED

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMPTY_STATS = BatchRegistryStats(total_jobs=1, completed=1, in_progress=0, failed=0, cancelled=0)


def _make_entry(
    batch_id: str = "batch-1",
    file_name: str = "file_a",
    record_count: int = 3,
) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=batch_id,
        status=BatchStatus.COMPLETED,
        timestamp="2026-05-19T00:00:00Z",
        provider="openai",
        record_count=record_count,
        file_name=file_name,
    )


def _make_context_map(*records: tuple[str, str, FilterStatus]) -> dict:
    """Build a context_map from (custom_id, source_guid, status) tuples."""
    ctx = {}
    for custom_id, source_guid, status in records:
        record: dict = {"source_guid": source_guid}
        BatchContextMetadata.set_filter_status(record, status)
        ctx[custom_id] = record
    return ctx


def _build_service(
    storage_backend: MagicMock | None = None,
    action_name: str = "test_action",
) -> BatchProcessingService:
    """Construct a BatchProcessingService with mocked dependencies."""
    svc = BatchProcessingService.__new__(BatchProcessingService)
    svc._client_resolver = MagicMock()
    svc._context_manager = MagicMock()
    svc._result_processor = MagicMock()
    svc._registry_manager_factory = MagicMock()
    svc._source_handler = None
    svc._action_indices = {}
    svc._dependency_configs = {}
    svc._storage_backend = storage_backend
    svc._workflow_name = action_name
    svc._retry_service = MagicMock()
    svc._enrichment_pipeline = MagicMock()
    return svc


def _setup_single_file_failure(
    svc: BatchProcessingService,
    *,
    file_name: str = "file_a",
    batch_id: str = "batch-1",
) -> MagicMock:
    """Wire up a single-file registry where _process_single_batch_file raises."""
    entry = _make_entry(batch_id=batch_id, file_name=file_name)
    manager = MagicMock()
    manager.get_all_jobs.return_value = {file_name: entry}
    manager.get_registry_stats.return_value = _EMPTY_STATS
    svc._registry_manager_factory.return_value = manager
    return manager


def _failed_disposition_record_ids(backend: MagicMock) -> set[str]:
    """Extract record_ids from set_disposition calls that wrote DISPOSITION_FAILED."""
    ids = set()
    for c in backend.set_disposition.call_args_list:
        # Handles both positional and keyword calling conventions
        disposition = c[0][2] if len(c[0]) > 2 else c.kwargs.get("disposition")
        if disposition == DISPOSITION_FAILED:
            ids.add(c[0][1])
    return ids


def _run_with_failure(svc, side_effect):
    """Patch _is_batch_ready + _process_single_batch_file, call process_all_batch_results."""
    with (
        patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
        patch.object(svc, "_process_single_batch_file", side_effect=side_effect),
    ):
        with pytest.raises(ProcessingError):
            svc.process_all_batch_results("/output")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBatchExceptionDisposition:
    """process_all_batch_results writes FAILED dispositions on exception."""

    def test_failed_batch_writes_failed_disposition_for_included_records(self):
        """INCLUDED records in a failed batch get DISPOSITION_FAILED."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)

        context_map = _make_context_map(
            ("t1", "sg-1", FilterStatus.INCLUDED),
            ("t2", "sg-2", FilterStatus.INCLUDED),
            ("t3", "sg-3", FilterStatus.SKIPPED),
        )
        svc._context_manager.load_batch_context_map.return_value = context_map
        _setup_single_file_failure(svc)
        _run_with_failure(svc, ValueError("simulated error"))

        failed_ids = _failed_disposition_record_ids(backend)
        assert failed_ids == {"sg-1", "sg-2"}

        cleared_ids = {c.kwargs.get("record_id") for c in backend.clear_disposition.call_args_list}
        assert "sg-1" in cleared_ids
        assert "sg-2" in cleared_ids
        assert "sg-3" not in cleared_ids

    def test_failed_batch_reason_contains_exception_message(self):
        """FAILED disposition reason includes the exception message."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)

        context_map = _make_context_map(("t1", "sg-1", FilterStatus.INCLUDED))
        svc._context_manager.load_batch_context_map.return_value = context_map
        _setup_single_file_failure(svc, file_name="file_x", batch_id="batch-x")
        _run_with_failure(svc, TypeError("unexpected None"))

        set_call = backend.set_disposition.call_args
        assert "unexpected None" in set_call.kwargs.get("reason", "")

    def test_other_files_unaffected_by_single_file_failure(self):
        """When one batch file fails, other files still process normally."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)

        ctx_a = _make_context_map(("t1", "sg-1", FilterStatus.INCLUDED))
        ctx_b = _make_context_map(("t2", "sg-2", FilterStatus.INCLUDED))

        def load_context(backend, action_name, file_name):
            return ctx_a if file_name == "file_a" else ctx_b

        svc._context_manager.load_batch_context_map.side_effect = load_context

        entry_a = _make_entry(batch_id="batch-a", file_name="file_a")
        entry_b = _make_entry(batch_id="batch-b", file_name="file_b")
        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file_a": entry_a, "file_b": entry_b}
        svc._registry_manager_factory.return_value = manager

        def process_side_effect(**kwargs):
            if kwargs["file_name"] == "file_a":
                raise ValueError("file_a broke")
            return "/output/file_b.json"

        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(svc, "_process_single_batch_file", side_effect=process_side_effect),
        ):
            result = svc.process_all_batch_results("/output")

        assert result == ["/output/file_b.json"]

        failed_ids = _failed_disposition_record_ids(backend)
        assert failed_ids == {"sg-1"}

    def test_no_disposition_when_no_storage_backend(self):
        """Without a storage backend, exception path doesn't crash."""
        svc = _build_service(storage_backend=None)
        _setup_single_file_failure(svc)
        _run_with_failure(svc, ValueError("boom"))

        svc._context_manager.load_batch_context_map.assert_not_called()

    def test_context_map_load_failure_does_not_crash(self):
        """If loading the context_map itself fails, we log and continue."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)
        svc._context_manager.load_batch_context_map.side_effect = OSError("disk error")
        _setup_single_file_failure(svc)
        _run_with_failure(svc, ValueError("processing failed"))

        backend.set_disposition.assert_not_called()

    def test_runtime_error_still_propagates(self):
        """RuntimeError must propagate (not be caught by the exception handler)."""
        svc = _build_service(storage_backend=MagicMock())
        _setup_single_file_failure(svc)

        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(svc, "_process_single_batch_file", side_effect=RuntimeError("fatal")),
        ):
            with pytest.raises(RuntimeError, match="fatal"):
                svc.process_all_batch_results("/output")

    def test_records_without_source_guid_skipped(self):
        """Records missing source_guid don't get dispositions (no crash)."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)

        ctx = {}
        record: dict = {}
        BatchContextMetadata.set_filter_status(record, FilterStatus.INCLUDED)
        ctx["t1"] = record
        svc._context_manager.load_batch_context_map.return_value = ctx

        _setup_single_file_failure(svc)
        _run_with_failure(svc, ValueError("boom"))

        backend.set_disposition.assert_not_called()
        backend.clear_disposition.assert_not_called()

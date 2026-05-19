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
    svc._action_name = action_name
    svc._retry_service = MagicMock()
    svc._enrichment_pipeline = MagicMock()
    return svc


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

        entry_a = _make_entry(batch_id="batch-a", file_name="file_a")
        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file_a": entry_a}
        manager.get_registry_stats.return_value = BatchRegistryStats(
            total_jobs=1, completed=1, in_progress=0, failed=0, cancelled=0
        )
        svc._registry_manager_factory.return_value = manager

        # Simulate _is_batch_ready_for_processing returning True, then
        # _process_single_batch_file raising a ValueError
        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(
                svc,
                "_process_single_batch_file",
                side_effect=ValueError("simulated error"),
            ),
        ):
            # Should raise ProcessingError because no files were processed
            with pytest.raises(ProcessingError):
                svc.process_all_batch_results("/output")

        # INCLUDED records get FAILED
        failed_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if c[0][2] == DISPOSITION_FAILED or c.kwargs.get("disposition") == DISPOSITION_FAILED
        ]
        assert len(failed_calls) == 2
        failed_ids = {c[0][1] for c in failed_calls}
        assert failed_ids == {"sg-1", "sg-2"}

        # DEFERRED cleared for INCLUDED records
        clear_calls = backend.clear_disposition.call_args_list
        cleared_ids = {c.kwargs.get("record_id") or c[0][1] for c in clear_calls}
        assert "sg-1" in cleared_ids
        assert "sg-2" in cleared_ids
        # SKIPPED record sg-3 must NOT appear
        assert "sg-3" not in cleared_ids
        assert "sg-3" not in failed_ids

    def test_failed_batch_reason_contains_exception_message(self):
        """FAILED disposition reason includes the exception message."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)

        context_map = _make_context_map(("t1", "sg-1", FilterStatus.INCLUDED))
        svc._context_manager.load_batch_context_map.return_value = context_map

        entry = _make_entry(batch_id="batch-x", file_name="file_x")
        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file_x": entry}
        manager.get_registry_stats.return_value = BatchRegistryStats(
            total_jobs=1, completed=1, in_progress=0, failed=0, cancelled=0
        )
        svc._registry_manager_factory.return_value = manager

        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(
                svc,
                "_process_single_batch_file",
                side_effect=TypeError("unexpected None"),
            ),
        ):
            with pytest.raises(ProcessingError):
                svc.process_all_batch_results("/output")

        # Check reason
        set_call = backend.set_disposition.call_args
        assert "unexpected None" in set_call.kwargs.get("reason", set_call[1].get("reason", ""))

    def test_other_files_unaffected_by_single_file_failure(self):
        """When one batch file fails, other files still process normally."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)

        # file_a will fail, file_b will succeed
        ctx_a = _make_context_map(("t1", "sg-1", FilterStatus.INCLUDED))
        ctx_b = _make_context_map(("t2", "sg-2", FilterStatus.INCLUDED))

        def load_context(output_dir, file_name):
            return ctx_a if file_name == "file_a" else ctx_b

        svc._context_manager.load_batch_context_map.side_effect = load_context

        entry_a = _make_entry(batch_id="batch-a", file_name="file_a")
        entry_b = _make_entry(batch_id="batch-b", file_name="file_b")
        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file_a": entry_a, "file_b": entry_b}
        svc._registry_manager_factory.return_value = manager

        call_count = 0

        def process_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs["file_name"] == "file_a":
                raise ValueError("file_a broke")
            return "/output/file_b.json"

        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(
                svc,
                "_process_single_batch_file",
                side_effect=process_side_effect,
            ),
        ):
            result = svc.process_all_batch_results("/output")

        # file_b processed successfully
        assert result == ["/output/file_b.json"]

        # Only file_a's records got FAILED dispositions
        failed_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if len(c[0]) > 2 and c[0][2] == DISPOSITION_FAILED
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0][0][1] == "sg-1"

    def test_no_disposition_when_no_storage_backend(self):
        """Without a storage backend, exception path doesn't crash."""
        svc = _build_service(storage_backend=None)

        entry = _make_entry(batch_id="batch-1", file_name="file_a")
        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file_a": entry}
        manager.get_registry_stats.return_value = BatchRegistryStats(
            total_jobs=1, completed=1, in_progress=0, failed=0, cancelled=0
        )
        svc._registry_manager_factory.return_value = manager

        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(
                svc,
                "_process_single_batch_file",
                side_effect=ValueError("boom"),
            ),
        ):
            with pytest.raises(ProcessingError):
                svc.process_all_batch_results("/output")

        # No crash — context_manager should not even be called for context_map
        svc._context_manager.load_batch_context_map.assert_not_called()

    def test_context_map_load_failure_does_not_crash(self):
        """If loading the context_map itself fails, we log and continue."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)

        svc._context_manager.load_batch_context_map.side_effect = OSError("disk error")

        entry = _make_entry(batch_id="batch-1", file_name="file_a")
        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file_a": entry}
        manager.get_registry_stats.return_value = BatchRegistryStats(
            total_jobs=1, completed=1, in_progress=0, failed=0, cancelled=0
        )
        svc._registry_manager_factory.return_value = manager

        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(
                svc,
                "_process_single_batch_file",
                side_effect=ValueError("processing failed"),
            ),
        ):
            with pytest.raises(ProcessingError):
                svc.process_all_batch_results("/output")

        # No disposition writes since context_map couldn't be loaded
        backend.set_disposition.assert_not_called()

    def test_runtime_error_still_propagates(self):
        """RuntimeError must propagate (not be caught by the exception handler)."""
        svc = _build_service(storage_backend=MagicMock())

        entry = _make_entry(batch_id="batch-1", file_name="file_a")
        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file_a": entry}
        svc._registry_manager_factory.return_value = manager

        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(
                svc,
                "_process_single_batch_file",
                side_effect=RuntimeError("fatal"),
            ),
        ):
            with pytest.raises(RuntimeError, match="fatal"):
                svc.process_all_batch_results("/output")

    def test_records_without_source_guid_skipped(self):
        """Records missing source_guid don't get dispositions (no crash)."""
        backend = MagicMock()
        svc = _build_service(storage_backend=backend)

        # Record with no source_guid
        ctx = {}
        record: dict = {}
        BatchContextMetadata.set_filter_status(record, FilterStatus.INCLUDED)
        ctx["t1"] = record

        svc._context_manager.load_batch_context_map.return_value = ctx

        entry = _make_entry(batch_id="batch-1", file_name="file_a")
        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file_a": entry}
        manager.get_registry_stats.return_value = BatchRegistryStats(
            total_jobs=1, completed=1, in_progress=0, failed=0, cancelled=0
        )
        svc._registry_manager_factory.return_value = manager

        with (
            patch.object(svc, "_is_batch_ready_for_processing", return_value=True),
            patch.object(
                svc,
                "_process_single_batch_file",
                side_effect=ValueError("boom"),
            ),
        ):
            with pytest.raises(ProcessingError):
                svc.process_all_batch_results("/output")

        # No disposition writes for records without source_guid
        backend.set_disposition.assert_not_called()
        backend.clear_disposition.assert_not_called()

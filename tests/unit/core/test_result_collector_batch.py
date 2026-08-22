"""Tests for batch disposition flush in collect_results_from_processing_results."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from agent_actions.processing.result_collector import (
    collect_results_from_processing_results,
)
from agent_actions.processing.types import ProcessingResult, ProcessingStatus
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
)


def _mock_backend() -> MagicMock:
    backend = MagicMock()
    backend.set_dispositions_batch = MagicMock()
    backend.set_disposition = MagicMock()
    return backend


class TestBatchDispositionFlush:
    """Verify collect_results_from_processing_results flushes dispositions in a single batch."""

    def test_success_results_batched(self):
        """Multiple SUCCESS results should produce one set_dispositions_batch call."""
        backend = _mock_backend()
        results = [
            ProcessingResult.success(data=[{"content": {"v": i}}], source_guid=f"rec_{i}")
            for i in range(5)
        ]
        collect_results_from_processing_results(results, "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 5
        assert all(t[2] == DISPOSITION_SUCCESS for t in batch_arg)

    def test_mixed_statuses_batched_together(self):
        """Different statuses should all land in a single batch call."""
        backend = _mock_backend()
        results = [
            ProcessingResult.success(data=[{"content": {"v": 1}}], source_guid="s1"),
            ProcessingResult.failed(error="boom", source_guid="s2"),
            ProcessingResult.skipped(passthrough_data={"v": 3}, reason="guard", source_guid="s3"),
            ProcessingResult(
                status=ProcessingStatus.FILTERED,
                data=[],
                source_guid="s4",
                skip_reason="filter",
            ),
            ProcessingResult(
                status=ProcessingStatus.UNPROCESSED,
                data=[{"source_guid": "s5"}],
                source_guid="s5",
                skip_reason="cascade",
            ),
            ProcessingResult.deferred(task_id="task-123", source_guid="s6"),
        ]
        collect_results_from_processing_results(results, "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 6
        dispositions = [t[2] for t in batch_arg]
        assert DISPOSITION_SUCCESS in dispositions
        assert DISPOSITION_FAILED in dispositions
        assert DISPOSITION_PASSTHROUGH in dispositions
        assert DISPOSITION_FILTERED in dispositions
        assert DISPOSITION_UNPROCESSED in dispositions
        assert DISPOSITION_DEFERRED in dispositions

    def test_no_backend_no_batch_call(self):
        """Without a storage backend, no batch call should happen."""
        results = [
            ProcessingResult.success(data=[{"content": {"v": 1}}], source_guid="s1"),
        ]
        # Should not raise.
        output, stats = collect_results_from_processing_results(
            results, "action_A", storage_backend=None
        )
        assert stats.success == 1

    def test_no_source_guid_no_disposition(self):
        """Results without source_guid should not produce disposition entries."""
        backend = _mock_backend()
        results = [
            ProcessingResult.success(data=[{"content": {"v": 1}}], source_guid=None),
        ]
        collect_results_from_processing_results(results, "action_A", storage_backend=backend)
        # No dispositions accumulated (source_guid is None, no FILE-mode items).
        backend.set_dispositions_batch.assert_not_called()

    def test_batch_failure_logged_not_raised(self):
        """If set_dispositions_batch raises, it should be caught and logged, not crash."""
        backend = _mock_backend()
        backend.set_dispositions_batch.side_effect = RuntimeError("DB gone")
        results = [
            ProcessingResult.success(data=[{"content": {"v": 1}}], source_guid="s1"),
        ]
        # Should not raise — disposition writes are telemetry.
        output, stats = collect_results_from_processing_results(
            results, "action_A", storage_backend=backend
        )
        assert stats.success == 1
        assert len(output) == 1

    def test_file_mode_per_item_dispositions(self):
        """FILE-mode results (source_guid=None on result, per-item guids) should batch per-item."""
        backend = _mock_backend()
        results = [
            ProcessingResult.success(
                data=[
                    {"content": {"v": 1}, "source_guid": "item_1"},
                    {"content": {"v": 2}, "source_guid": "item_2"},
                ],
                source_guid=None,
            ),
        ]
        collect_results_from_processing_results(results, "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 2
        record_ids = {t[1] for t in batch_arg}
        assert record_ids == {"item_1", "item_2"}

    def test_exhausted_includes_snapshot_and_detail(self):
        """EXHAUSTED disposition should carry input_snapshot and detail."""
        backend = _mock_backend()
        from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

        result = ProcessingResult.exhausted(
            error="timeout",
            source_guid="s1",
            recovery_metadata=RecoveryMetadata(
                retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="timeout")
            ),
        )
        result.data = [{"source_guid": "s1", "content": {}}]
        result.source_snapshot = {"key": "value"}

        collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 1
        t = batch_arg[0]
        assert t[2] == DISPOSITION_EXHAUSTED
        assert "exhausted_after_3_attempts" in t[3]  # reason
        assert t[5] is not None  # input_snapshot
        assert t[6] == "timeout"  # detail

    def test_per_record_set_disposition_not_called(self):
        """The per-record _safe_set_disposition path should NOT be used inside collect_results."""
        backend = _mock_backend()
        results = [
            ProcessingResult.success(data=[{"content": {"v": 1}}], source_guid="s1"),
            ProcessingResult.failed(error="err", source_guid="s2"),
        ]
        collect_results_from_processing_results(results, "action_A", storage_backend=backend)
        # set_disposition (single-record) should NOT be called — only set_dispositions_batch.
        backend.set_disposition.assert_not_called()


class TestWriteRecordDispositionsWarning:
    """write_record_dispositions logs a warning when batch items lack source_guid."""

    def test_missing_source_guid_logs_warning(self, caplog):
        """Batch items without source_guid log a warning instead of silent skip."""
        from agent_actions.processing.result_collector import write_record_dispositions

        backend = _mock_backend()
        items = [
            {"metadata": {}, "content": {"v": 1}},
        ]
        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.result_collector"):
            write_record_dispositions(backend, items, "action_A")
        assert any("missing source_guid" in r.message for r in caplog.records)
        backend.set_disposition.assert_not_called()

    def test_items_with_source_guid_still_work(self):
        """Batch items with source_guid are processed normally."""
        from agent_actions.processing.result_collector import write_record_dispositions

        backend = _mock_backend()
        items = [
            {"source_guid": "sg-1", "metadata": {}, "_state": "processed"},
        ]
        write_record_dispositions(backend, items, "action_A")
        backend.set_disposition.assert_called_once()


class TestPerItemDispositionFallback:
    """When result.source_guid is None but data items carry their own source_guid,
    dispositions must be written per-item to prevent infinite reprocessing."""

    def test_skipped_per_item_dispositions(self):
        """SKIPPED results with source_guid=None write per-item PASSTHROUGH dispositions."""
        backend = _mock_backend()
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="guard_skip",
            source_guid=None,
        )
        result.data = [
            {"source_guid": "item_1", "content": {}},
            {"source_guid": "item_2", "content": {}},
        ]
        collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 2
        assert all(t[2] == DISPOSITION_PASSTHROUGH for t in batch_arg)
        assert {t[1] for t in batch_arg} == {"item_1", "item_2"}

    def test_failed_per_item_dispositions(self):
        """FAILED results with source_guid=None write per-item FAILED dispositions."""
        backend = _mock_backend()
        result = ProcessingResult.failed(error="timeout", source_guid=None)
        result.data = [
            {"source_guid": "item_1", "error": "timeout"},
            {"source_guid": "item_2", "error": "timeout"},
        ]
        collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 2
        assert all(t[2] == DISPOSITION_FAILED for t in batch_arg)
        assert {t[1] for t in batch_arg} == {"item_1", "item_2"}

    def test_exhausted_per_item_dispositions(self):
        """EXHAUSTED results with source_guid=None write per-item EXHAUSTED dispositions."""
        backend = _mock_backend()
        from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

        result = ProcessingResult.exhausted(
            error="max_retries",
            source_guid=None,
            recovery_metadata=RecoveryMetadata(
                retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="max_retries")
            ),
        )
        result.data = [
            {"source_guid": "item_1", "content": {}},
        ]
        collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 1
        assert batch_arg[0][1] == "item_1"
        assert batch_arg[0][2] == DISPOSITION_EXHAUSTED

    def test_unprocessed_per_item_dispositions(self):
        """UNPROCESSED results with source_guid=None write per-item UNPROCESSED dispositions."""
        backend = _mock_backend()
        result = ProcessingResult(
            status=ProcessingStatus.UNPROCESSED,
            data=[
                {"source_guid": "item_1"},
                {"source_guid": "item_2"},
            ],
            source_guid=None,
            skip_reason="cascade_blocked",
        )
        collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 2
        assert all(t[2] == DISPOSITION_UNPROCESSED for t in batch_arg)
        assert {t[1] for t in batch_arg} == {"item_1", "item_2"}

    def test_parse_error_per_item_dispositions(self):
        """Parse-error SUCCESS→FAILED with source_guid=None writes per-item FAILED dispositions."""
        backend = _mock_backend()
        result = ProcessingResult.success(
            data=[
                {"source_guid": "item_1", "content": {"ns": {"_parse_error": "bad"}}},
            ],
            source_guid=None,
        )
        collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 1
        assert batch_arg[0][1] == "item_1"
        assert batch_arg[0][2] == DISPOSITION_FAILED

    def test_filtered_per_item_dispositions(self):
        """FILTERED results with source_guid=None write per-item FILTERED dispositions."""
        backend = _mock_backend()
        result = ProcessingResult(
            status=ProcessingStatus.FILTERED,
            data=[
                {"source_guid": "item_1"},
                {"source_guid": "item_2"},
            ],
            source_guid=None,
            skip_reason="guard_filter",
        )
        collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 2
        assert all(t[2] == DISPOSITION_FILTERED for t in batch_arg)
        assert {t[1] for t in batch_arg} == {"item_1", "item_2"}

    def test_filtered_no_data_no_source_guid_logs_warning(self, caplog):
        """FILTERED result with no source_guid and no data logs a warning."""
        backend = _mock_backend()
        result = ProcessingResult(
            status=ProcessingStatus.FILTERED,
            data=[],
            source_guid=None,
        )
        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.result_collector"):
            collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        assert any("FILTERED result has no source_guid" in r.message for r in caplog.records)
        backend.set_dispositions_batch.assert_not_called()

    def test_deferred_no_source_guid_logs_warning(self, caplog):
        """DEFERRED result with no source_guid logs a warning."""
        backend = _mock_backend()
        result = ProcessingResult.deferred(task_id="task-1", source_guid=None)
        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.result_collector"):
            collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        assert any("DEFERRED result has no source_guid" in r.message for r in caplog.records)
        backend.set_dispositions_batch.assert_not_called()

    def test_failed_no_data_no_source_guid_logs_warning(self, caplog):
        """FAILED result with no source_guid and no data logs a warning."""
        backend = _mock_backend()
        result = ProcessingResult.failed(error="timeout", source_guid=None)
        result.data = []
        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.result_collector"):
            collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        assert any("FAILED result has no source_guid" in r.message for r in caplog.records)

    def test_mixed_items_with_and_without_guid(self):
        """Only items with source_guid get dispositions; those without are warned about."""
        backend = _mock_backend()
        result = ProcessingResult.success(
            data=[
                {"source_guid": "item_1", "content": {"v": 1}},
                {"content": {"v": 2}},
            ],
            source_guid=None,
        )
        collect_results_from_processing_results([result], "action_A", storage_backend=backend)
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert len(batch_arg) == 1
        assert batch_arg[0][1] == "item_1"

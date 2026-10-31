"""Tests for batch disposition flush in collect_results_from_processing_results."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from agent_actions.processing.result_collector import (
    collect_results_from_processing_results,
)
from agent_actions.processing.types import (
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)
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


def _skipped_without_guid() -> ProcessingResult:
    result = ProcessingResult.skipped(passthrough_data=None, reason="guard_skip", source_guid=None)
    result.data = [
        {"source_guid": "item_1", "content": {}},
        {"source_guid": "item_2", "content": {}},
    ]
    return result


def _failed_without_guid() -> ProcessingResult:
    result = ProcessingResult.failed(error="timeout", source_guid=None)
    result.data = [
        {"source_guid": "item_1", "error": "timeout"},
        {"source_guid": "item_2", "error": "timeout"},
    ]
    return result


def _failed_without_guid_or_data() -> ProcessingResult:
    result = ProcessingResult.failed(error="timeout", source_guid=None)
    result.data = []
    return result


def _exhausted_without_guid() -> ProcessingResult:
    result = ProcessingResult.exhausted(
        error="max_retries",
        source_guid=None,
        recovery_metadata=RecoveryMetadata(
            retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="max_retries")
        ),
    )
    result.data = [{"source_guid": "item_1", "content": {}}]
    return result


class TestPerItemDispositionFallback:
    """When result.source_guid is None but data items carry their own source_guid,
    dispositions must be written per-item to prevent infinite reprocessing."""

    @pytest.mark.parametrize(
        ("make_result", "expected"),
        [
            pytest.param(
                _skipped_without_guid,
                [("item_1", DISPOSITION_PASSTHROUGH), ("item_2", DISPOSITION_PASSTHROUGH)],
                id="skipped-passthrough",
            ),
            pytest.param(
                _failed_without_guid,
                [("item_1", DISPOSITION_FAILED), ("item_2", DISPOSITION_FAILED)],
                id="failed",
            ),
            pytest.param(
                _exhausted_without_guid, [("item_1", DISPOSITION_EXHAUSTED)], id="exhausted"
            ),
            pytest.param(
                lambda: ProcessingResult(
                    status=ProcessingStatus.UNPROCESSED,
                    data=[{"source_guid": "item_1"}, {"source_guid": "item_2"}],
                    source_guid=None,
                    skip_reason="cascade_blocked",
                ),
                [("item_1", DISPOSITION_UNPROCESSED), ("item_2", DISPOSITION_UNPROCESSED)],
                id="unprocessed",
            ),
            # A SUCCESS whose item carries a parse error is turned into FAILED.
            pytest.param(
                lambda: ProcessingResult.success(
                    data=[{"source_guid": "item_1", "content": {"ns": {"_parse_error": "bad"}}}],
                    source_guid=None,
                ),
                [("item_1", DISPOSITION_FAILED)],
                id="parse-error-failed",
            ),
            pytest.param(
                lambda: ProcessingResult(
                    status=ProcessingStatus.FILTERED,
                    data=[{"source_guid": "item_1"}, {"source_guid": "item_2"}],
                    source_guid=None,
                    skip_reason="guard_filter",
                ),
                [("item_1", DISPOSITION_FILTERED), ("item_2", DISPOSITION_FILTERED)],
                id="filtered",
            ),
        ],
    )
    def test_result_without_guid_writes_per_item_dispositions(self, make_result, expected):
        backend = _mock_backend()
        collect_results_from_processing_results(
            [make_result()], "action_A", storage_backend=backend
        )
        backend.set_dispositions_batch.assert_called_once()
        batch_arg = backend.set_dispositions_batch.call_args[0][0]
        assert sorted((t[1], t[2]) for t in batch_arg) == expected

    @pytest.mark.parametrize(
        ("make_result", "needle"),
        [
            pytest.param(
                lambda: ProcessingResult(
                    status=ProcessingStatus.FILTERED, data=[], source_guid=None
                ),
                "FILTERED result has no source_guid",
                id="filtered-no-data",
            ),
            pytest.param(
                lambda: ProcessingResult.deferred(task_id="task-1", source_guid=None),
                "DEFERRED result has no source_guid",
                id="deferred",
            ),
            pytest.param(
                _failed_without_guid_or_data,
                "FAILED result has no source_guid",
                id="failed-no-data",
            ),
        ],
    )
    def test_result_without_guid_or_items_logs_warning(self, caplog, make_result, needle):
        backend = _mock_backend()
        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.result_collector"):
            collect_results_from_processing_results(
                [make_result()], "action_A", storage_backend=backend
            )
        assert any(needle in r.message for r in caplog.records)
        backend.set_dispositions_batch.assert_not_called()

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

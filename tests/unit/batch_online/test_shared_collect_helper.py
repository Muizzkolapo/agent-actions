"""Phase 8a: Shared collect helper — extraction parity tests.

Tests that the extracted ``collect_results_from_processing_results()``
produces identical output to ``ResultCollector.collect_results()`` for
all status paths: SUCCESS, FAILED, EXHAUSTED, SKIPPED, FILTERED,
UNPROCESSED, DEFERRED.

These tests exercise the shared helper directly and verify it against
the batch retrieve scenario where ProcessingResult objects arrive
with mixed statuses (as they do from BatchResultStrategy.process).
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.processing.record_helpers import build_tombstone
from agent_actions.processing.result_collector import (
    ResultCollector,
    collect_results_from_processing_results,
)
from agent_actions.processing.types import ProcessingResult
from agent_actions.record.reasons import (
    GUARD_SKIP,
    UNPROCESSED,
)
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import (
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
)

ACTION_NAME = "test_action"


def _make_success_result(source_guid: str = "sg-001") -> ProcessingResult:
    """Create a SUCCESS ProcessingResult mimicking batch retrieve output."""
    return ProcessingResult.success(
        data=[
            {
                "target_id": f"t-{source_guid}",
                "source_guid": source_guid,
                "content": {"ns": {"field": "value"}},
            }
        ],
        source_guid=source_guid,
    )


def _make_failed_result(
    source_guid: str = "sg-002", error: str = "LLM timeout"
) -> ProcessingResult:
    """Create a FAILED ProcessingResult."""
    return ProcessingResult.failed(
        error=error,
        source_guid=source_guid,
        input_record={"target_id": f"t-{source_guid}", "source_guid": source_guid},
    )


def _make_exhausted_result(source_guid: str = "sg-003") -> ProcessingResult:
    """Create an EXHAUSTED ProcessingResult with retry metadata."""
    return ProcessingResult.exhausted(
        error="max retries exceeded",
        data=[
            {
                "target_id": f"t-{source_guid}",
                "source_guid": source_guid,
                "content": {"ns": {"field": "partial"}},
                "metadata": {"retry_exhausted": True},
            }
        ],
        source_guid=source_guid,
    )


def _make_skipped_result(source_guid: str = "sg-004") -> ProcessingResult:
    """Create a SKIPPED ProcessingResult (guard skip with tombstone)."""
    tombstone = build_tombstone(
        ACTION_NAME,
        {"target_id": f"t-{source_guid}", "source_guid": source_guid},
        GUARD_SKIP,
        source_guid=source_guid,
    )
    return ProcessingResult.skipped(
        passthrough_data=tombstone,
        reason=GUARD_SKIP,
        source_guid=source_guid,
    )


def _make_filtered_result() -> ProcessingResult:
    """Create a FILTERED ProcessingResult (guard filter, no output)."""
    return ProcessingResult.filtered(source_guid=None)


def _make_unprocessed_result(source_guid: str = "sg-006") -> ProcessingResult:
    """Create an UNPROCESSED ProcessingResult (upstream cascade)."""
    tombstone = build_tombstone(
        ACTION_NAME,
        {"target_id": f"t-{source_guid}", "source_guid": source_guid},
        UNPROCESSED,
        source_guid=source_guid,
    )
    return ProcessingResult.unprocessed(
        data=[tombstone],
        reason=UNPROCESSED,
        source_guid=source_guid,
    )


def _make_deferred_result(
    source_guid: str = "sg-007", task_id: str = "batch-task-123"
) -> ProcessingResult:
    """Create a DEFERRED ProcessingResult."""
    return ProcessingResult.deferred(
        task_id=task_id,
        source_guid=source_guid,
    )


def _mock_storage_backend() -> MagicMock:
    return MagicMock()


class TestSharedHelperParityWithCollectResults:
    """Shared helper must produce identical (records, stats) to ResultCollector."""

    def test_success_records(self):
        """SUCCESS results produce PROCESSED state and SUCCESS disposition."""
        results = [_make_success_result("sg-001")]
        backend = _mock_storage_backend()

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            storage_backend=backend,
        )

        assert len(records) == 1
        assert records[0]["_state"] == RecordState.PROCESSED.value
        assert stats.success == 1
        backend.set_disposition.assert_called_once()
        call_args = backend.set_disposition.call_args
        assert call_args[0][2] == DISPOSITION_SUCCESS

    def test_failed_records(self):
        """FAILED results produce tombstone with FAILED state and disposition."""
        results = [_make_failed_result("sg-002")]
        backend = _mock_storage_backend()

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            storage_backend=backend,
        )

        assert len(records) == 1
        assert records[0]["_state"] == RecordState.FAILED.value
        assert records[0].get("metadata", {}).get("agent_type") == "tombstone"
        assert stats.failed == 1
        backend.set_disposition.assert_called_once()
        call_args = backend.set_disposition.call_args
        assert call_args[0][2] == DISPOSITION_FAILED

    def test_exhausted_records(self):
        """EXHAUSTED results get EXHAUSTED state and disposition."""
        results = [_make_exhausted_result("sg-003")]
        backend = _mock_storage_backend()

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            storage_backend=backend,
        )

        assert len(records) == 1
        assert records[0]["_state"] == RecordState.EXHAUSTED.value
        assert stats.exhausted == 1
        backend.set_disposition.assert_called_once()
        call_args = backend.set_disposition.call_args
        assert call_args[0][2] == DISPOSITION_EXHAUSTED

    def test_skipped_records(self):
        """SKIPPED results get GUARD_SKIPPED state and PASSTHROUGH disposition."""
        results = [_make_skipped_result("sg-004")]
        backend = _mock_storage_backend()

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            storage_backend=backend,
        )

        assert len(records) == 1
        assert records[0]["_state"] == RecordState.GUARD_SKIPPED.value
        assert stats.skipped == 1
        backend.set_disposition.assert_called_once()
        call_args = backend.set_disposition.call_args
        assert call_args[0][2] == DISPOSITION_PASSTHROUGH

    def test_filtered_records(self):
        """FILTERED results produce no output records but count in stats."""
        results = [_make_filtered_result()]

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
        )

        assert len(records) == 0
        assert stats.filtered == 1

    def test_unprocessed_records(self):
        """UNPROCESSED results get CASCADE_SKIPPED state and disposition."""
        results = [_make_unprocessed_result("sg-006")]
        backend = _mock_storage_backend()

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            storage_backend=backend,
        )

        assert len(records) == 1
        assert records[0]["_state"] == RecordState.CASCADE_SKIPPED.value
        assert stats.unprocessed == 1
        backend.set_disposition.assert_called_once()
        call_args = backend.set_disposition.call_args
        assert call_args[0][2] == DISPOSITION_UNPROCESSED

    def test_deferred_records(self):
        """DEFERRED results produce no output but count in stats."""
        results = [_make_deferred_result("sg-007")]
        backend = _mock_storage_backend()

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            storage_backend=backend,
        )

        assert len(records) == 0
        assert stats.deferred == 1

    def test_mixed_batch_scenario(self):
        """Batch retrieve scenario: mixed SUCCESS + FAILED + EXHAUSTED + UNPROCESSED.

        This mimics the output of BatchResultStrategy.process() after enrichment,
        where a batch of records produces various outcomes.
        """
        results = [
            _make_success_result("sg-001"),
            _make_success_result("sg-002"),
            _make_failed_result("sg-003"),
            _make_exhausted_result("sg-004"),
            _make_unprocessed_result("sg-005"),
        ]
        backend = _mock_storage_backend()

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            storage_backend=backend,
        )

        assert len(records) == 5
        assert stats.success == 2
        assert stats.failed == 1
        assert stats.exhausted == 1
        assert stats.unprocessed == 1

    def test_no_storage_backend(self):
        """Helper works without a storage backend (no dispositions written)."""
        results = [_make_success_result("sg-001"), _make_failed_result("sg-002")]

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            storage_backend=None,
        )

        assert len(records) == 2
        assert stats.success == 1
        assert stats.failed == 1


class TestSharedHelperEquivalence:
    """Shared helper and ResultCollector.collect_results produce identical output."""

    def test_equivalent_output_for_mixed_results(self):
        """Same input through both APIs produces same records and stats."""
        results_a = [
            _make_success_result("sg-001"),
            _make_failed_result("sg-002"),
            _make_skipped_result("sg-003"),
        ]
        results_b = [
            _make_success_result("sg-001"),
            _make_failed_result("sg-002"),
            _make_skipped_result("sg-003"),
        ]

        agent_config = {"name": ACTION_NAME}

        # Via shared helper
        records_helper, stats_helper = collect_results_from_processing_results(
            results_a,
            ACTION_NAME,
            agent_config=agent_config,
        )

        # Via ResultCollector
        records_collector, stats_collector = ResultCollector.collect_results(
            results_b,
            agent_config,
            ACTION_NAME,
            is_first_stage=False,
        )

        # Same number of records
        assert len(records_helper) == len(records_collector)

        # Same stats
        assert stats_helper.success == stats_collector.success
        assert stats_helper.failed == stats_collector.failed
        assert stats_helper.skipped == stats_collector.skipped
        assert stats_helper.filtered == stats_collector.filtered
        assert stats_helper.exhausted == stats_collector.exhausted

        for rh, rc in zip(records_helper, records_collector, strict=True):
            assert rh["_state"] == rc["_state"]


class TestExhaustedRaiseGuard:
    """The exhausted-raise check depends on agent_config presence."""

    def test_exhausted_raise_with_config(self):
        """on_exhausted=raise + agent_config raises AgentActionsError."""
        results = [_make_exhausted_result("sg-001")]
        config = {"retry": {"on_exhausted": "raise"}}

        with pytest.raises(AgentActionsError, match="Retry exhausted"):
            collect_results_from_processing_results(
                results,
                ACTION_NAME,
                agent_config=config,
            )

    def test_exhausted_no_raise_without_config(self):
        """agent_config=None skips exhausted-raise (batch retrieve path)."""
        results = [_make_exhausted_result("sg-001")]

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            agent_config=None,
        )

        assert stats.exhausted == 1
        assert len(records) == 1

    def test_exhausted_raise_with_empty_config(self):
        """agent_config={} still checks exhausted-raise (returns normally, no raise config)."""
        results = [_make_exhausted_result("sg-001")]

        records, stats = collect_results_from_processing_results(
            results,
            ACTION_NAME,
            agent_config={},
        )

        assert stats.exhausted == 1
        assert len(records) == 1

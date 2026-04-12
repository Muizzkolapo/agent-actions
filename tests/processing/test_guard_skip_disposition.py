"""Regression tests for guard skip disposition.

When a guard evaluates to false with on_false=skip, the record must
get ProcessingStatus.SKIPPED (not UNPROCESSED) and storage must receive
DISPOSITION_SKIPPED.

Bug: specs/new/037-guard-skip-disposition-fix.md
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.prepared_task import GuardStatus, PreparedTask
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.storage.backend import DISPOSITION_SKIPPED, DISPOSITION_UNPROCESSED


@pytest.fixture
def guard_skip_prepared():
    """A PreparedTask where guard evaluated to SKIPPED."""
    prepared = MagicMock(spec=PreparedTask)
    prepared.guard_status = GuardStatus.SKIPPED
    prepared.guard_behavior = "skip"
    prepared.content = {"field": "value"}
    prepared.original_content = {"field": "value"}
    prepared.input_record = {"source_guid": "guid-1", "content": {"field": "value"}}
    prepared.source_guid = "guid-1"
    prepared.source_snapshot = {"field": "value"}
    return prepared


@pytest.fixture
def processing_context():
    """A minimal ProcessingContext for the guard skip path."""
    return ProcessingContext(
        agent_config={"agent_type": "test_action", "kind": "llm"},
        agent_name="test_action",
        record_index=0,
    )


@pytest.fixture
def record_processor():
    """Create a RecordProcessor with mocked strategy to avoid LLM init."""
    from agent_actions.processing.record_processor import RecordProcessor

    processor = RecordProcessor(
        agent_config={"agent_type": "test_action", "kind": "llm"},
        agent_name="test_action",
        strategy=MagicMock(),
    )
    return processor


class TestGuardSkipProducesSkippedStatus:
    """Guard skip must produce ProcessingStatus.SKIPPED, not UNPROCESSED."""

    def test_guard_skip_result_is_skipped(
        self, record_processor, guard_skip_prepared, processing_context
    ):
        """ProcessingResult.status == SKIPPED when guard skips the record."""
        mock_preparer = MagicMock()
        mock_preparer.prepare.return_value = guard_skip_prepared

        with patch(
            "agent_actions.processing.record_processor.get_task_preparer",
            return_value=mock_preparer,
        ):
            result = record_processor.process(
                {"source_guid": "guid-1", "content": {"field": "value"}},
                processing_context,
            )

        assert result.status == ProcessingStatus.SKIPPED

    def test_guard_skip_result_is_not_unprocessed(
        self, record_processor, guard_skip_prepared, processing_context
    ):
        """Explicitly verify the result is NOT UNPROCESSED — the old broken behavior."""
        mock_preparer = MagicMock()
        mock_preparer.prepare.return_value = guard_skip_prepared

        with patch(
            "agent_actions.processing.record_processor.get_task_preparer",
            return_value=mock_preparer,
        ):
            result = record_processor.process(
                {"source_guid": "guid-1", "content": {"field": "value"}},
                processing_context,
            )

        assert result.status != ProcessingStatus.UNPROCESSED


class TestGuardSkipDisposition:
    """Storage backend receives DISPOSITION_SKIPPED for guard-skipped records."""

    def test_skipped_result_gets_disposition_skipped(self):
        """ResultCollector writes DISPOSITION_SKIPPED for SKIPPED results."""
        result = ProcessingResult.skipped(
            passthrough_data={"content": {}, "source_guid": "guid-1", "_unprocessed": True},
            reason="guard_skip",
            source_guid="guid-1",
        )
        backend = MagicMock()

        ResultCollector.collect_results(
            [result],
            {"kind": "llm"},
            "test_action",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "test_action",
            "guid-1",
            DISPOSITION_SKIPPED,
            reason="guard_skip",
        )

    def test_skipped_result_does_not_get_unprocessed_disposition(self):
        """Verify DISPOSITION_UNPROCESSED is NOT written for guard-skipped records."""
        result = ProcessingResult.skipped(
            passthrough_data={"content": {}, "_unprocessed": True},
            reason="guard_skip",
            source_guid="guid-1",
        )
        backend = MagicMock()

        ResultCollector.collect_results(
            [result],
            {"kind": "llm"},
            "test_action",
            is_first_stage=False,
            storage_backend=backend,
        )

        for call in backend.set_disposition.call_args_list:
            assert call.args[2] != DISPOSITION_UNPROCESSED


class TestGuardSkipPreservesData:
    """Guard-skipped records retain source_guid and tombstone data."""

    def test_guard_skip_preserves_source_guid(
        self, record_processor, guard_skip_prepared, processing_context
    ):
        """source_guid flows through the SKIPPED result from process()."""
        mock_preparer = MagicMock()
        mock_preparer.prepare.return_value = guard_skip_prepared

        with patch(
            "agent_actions.processing.record_processor.get_task_preparer",
            return_value=mock_preparer,
        ):
            result = record_processor.process(
                {"source_guid": "guid-1", "content": {"field": "value"}},
                processing_context,
            )

        assert result.source_guid == "guid-1"

    def test_guard_skip_preserves_tombstone_data(self):
        """Tombstone dict is preserved in result.data as a single-element list."""
        tombstone = {
            "content": {"field": "value"},
            "source_guid": "guid-1",
            "metadata": {"reason": "guard_skip", "agent_type": "tombstone"},
            "_unprocessed": True,
        }
        result = ProcessingResult.skipped(
            passthrough_data=tombstone,
            reason="guard_skip",
            source_guid="guid-1",
        )
        assert result.data == [tombstone]

    def test_guard_skip_reason_preserved(
        self, record_processor, guard_skip_prepared, processing_context
    ):
        """skip_reason carries the guard behavior string."""
        mock_preparer = MagicMock()
        mock_preparer.prepare.return_value = guard_skip_prepared

        with patch(
            "agent_actions.processing.record_processor.get_task_preparer",
            return_value=mock_preparer,
        ):
            result = record_processor.process(
                {"source_guid": "guid-1", "content": {"field": "value"}},
                processing_context,
            )

        assert result.skip_reason == "guard_skip"

    def test_guard_skip_not_executed(self):
        """Guard-skipped results have executed=False."""
        result = ProcessingResult.skipped(
            passthrough_data={},
            reason="guard_skip",
        )
        assert result.executed is False


class TestGuardSkipLineageEnrichment:
    """Guard-skipped records must pass through enrichment (not be filtered out)."""

    def test_lineage_enricher_does_not_skip_skipped_status(self):
        """LineageEnricher.enrich() only skips FILTERED — SKIPPED gets enriched."""
        from agent_actions.processing.enrichment import LineageEnricher

        enricher = LineageEnricher()
        result = ProcessingResult.skipped(
            passthrough_data={"content": {}, "source_guid": "guid-1"},
            reason="guard_skip",
            source_guid="guid-1",
        )
        context = ProcessingContext(
            agent_config={"agent_type": "test"},
            agent_name="test_action",
            is_first_stage=True,
        )

        enriched = enricher.enrich(result, context)

        # FILTERED returns early (no enrichment). SKIPPED should be enriched —
        # the enricher adds lineage metadata to result.data items.
        assert enriched.status == ProcessingStatus.SKIPPED
        assert enriched.data
        assert "lineage" in enriched.data[0]

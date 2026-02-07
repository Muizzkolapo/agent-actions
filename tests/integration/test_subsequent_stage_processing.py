"""Integration tests for subsequent-stage processing (TargetContentProcessor replacement)."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.types import ProcessingContext, ProcessingMode, ProcessingStatus


class TestSubsequentStageBatchProcessing:
    """Test batch processing in subsequent-stage."""

    @patch.object(RecordProcessor, "process")
    def test_multiple_items_batch_processing(self, mock_process):
        """Batch processes multiple subsequent-stage items."""
        mock_process.side_effect = [
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 1}]),
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 2}]),
        ]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        items = [
            {"content": {"text": "item 1"}, "source_guid": "guid-1"},
            {"content": {"text": "item 2"}, "source_guid": "guid-2"},
        ]

        results = processor.process_batch(items, context)

        assert len(results) == 2
        assert mock_process.call_count == 2

"""Integration tests for first-stage processing (StagingProcessor replacement)."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.types import ProcessingContext, ProcessingMode, ProcessingStatus


class TestFirstStageBatchProcessing:
    """Test batch processing in first-stage."""

    @patch.object(RecordProcessor, "process")
    def test_multiple_items_batch_processing(self, mock_process):
        """Batch processes multiple first-stage items."""
        mock_process.side_effect = [
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 1}]),
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 2}]),
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 3}]),
        ]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        items = [
            {"text": "item 1"},
            {"text": "item 2"},
            {"text": "item 3"},
        ]

        results = processor.process_batch(items, context)

        assert len(results) == 3
        assert mock_process.call_count == 3

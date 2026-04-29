"""
Regression test for DataGenerator.create_agent_with_data handling UNPROCESSED status.

Bug: UNPROCESSED fell through to the SUCCESS branch, returning (data, True, ...)
which caused downstream stages to treat upstream-failed records as real outputs.
Fix: Explicit UNPROCESSED branch returns (data, False, ...).
"""

from unittest.mock import MagicMock

from agent_actions.processing.types import ProcessingResult
from agent_actions.prompt.data_generator import DataGenerator


class TestDataGeneratorUnprocessed:
    """Verify DataGenerator returns executed=False for UNPROCESSED records."""

    def _make_generator(self):
        config = {"agent_type": "test_action"}
        return DataGenerator(agent_config=config, agent_name="test_action")

    def test_unprocessed_returns_not_executed(self):
        """UNPROCESSED result must return executed=False, not fall through to SUCCESS."""
        gen = self._make_generator()

        unprocessed_data = [{"content": "stale", "_unprocessed": True}]
        mock_result = ProcessingResult.unprocessed(
            data=unprocessed_data,
            reason="upstream_unprocessed",
            source_guid="sg_1",
        )
        # Mock strategy and enrichment pipeline so we can control what process_record returns
        gen._online_strategy = MagicMock()
        gen._online_strategy.process_record.return_value = mock_result
        gen._enrichment_pipeline = MagicMock()
        gen._enrichment_pipeline.enrich.return_value = mock_result  # return unchanged

        item = {"content": "stale", "source_guid": "sg_1", "_unprocessed": True}
        data, executed, passthrough_fields = gen.create_agent_with_data(
            contents=item, current_item=item
        )

        assert executed is False, "UNPROCESSED records must not be marked as executed"
        assert data == unprocessed_data
        assert isinstance(passthrough_fields, dict)

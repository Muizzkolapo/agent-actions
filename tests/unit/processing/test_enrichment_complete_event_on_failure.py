"""EnrichmentPipelineCompleteEvent fires even when an enricher fails."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.enrichment import EnrichmentPipeline


class TestEnrichmentCompleteEventOnFailure:
    """EnrichmentPipelineCompleteEvent must fire even when an enricher fails."""

    def test_complete_event_fires_on_enricher_failure(self):
        events_fired = []

        class FailingEnricher:
            def enrich(self, result, context):
                raise RuntimeError("enricher boom")

        pipeline = EnrichmentPipeline(enrichers=[FailingEnricher()])

        with patch("agent_actions.processing.enrichment.fire_event") as mock_fire:
            with pytest.raises(RuntimeError, match="enricher boom"):
                pipeline.enrich(MagicMock(), MagicMock())

            # Collect event class names
            events_fired = [call.args[0].__class__.__name__ for call in mock_fire.call_args_list]

        assert "EnrichmentPipelineStartedEvent" in events_fired
        assert "EnrichmentPipelineCompleteEvent" in events_fired
        assert "EnricherExecutedEvent" in events_fired

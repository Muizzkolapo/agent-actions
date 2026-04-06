"""Wave 12 T1-1 regression: EnrichmentPipeline uses timezone-aware datetimes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus


def _make_result() -> ProcessingResult:
    return ProcessingResult(status=ProcessingStatus.SUCCESS)


def _make_context() -> ProcessingContext:
    return ProcessingContext(agent_name="test_action", agent_config={})


class TestEnrichmentPipelineUTC:
    """T1-1: elapsed_time must be computed with timezone-aware datetimes."""

    def test_enrich_does_not_raise_on_utc_subtraction(self):
        """EnrichmentPipeline.enrich() must not raise TypeError for datetime subtraction."""
        pipeline = EnrichmentPipeline()
        result = _make_result()
        context = _make_context()
        # TypeError would be raised here if one datetime is naive and other is aware
        enriched = pipeline.enrich(result, context)
        assert enriched.status == result.status
        assert enriched.data == result.data

    def test_utc_datetimes_are_timezone_aware(self):
        """datetime.now(UTC) must produce an offset-aware datetime."""
        now = datetime.now(UTC)
        assert now.tzinfo is not None

    def test_utc_datetime_subtraction_yields_non_negative_elapsed(self):
        """Two UTC datetimes can be subtracted without error."""
        start = datetime.now(UTC)
        end = datetime.now(UTC)
        elapsed = (end - start).total_seconds()
        assert elapsed >= 0.0

    def test_naive_datetime_subtraction_would_fail(self):
        """Verify that mixing naive and aware datetimes raises TypeError (proves why fix matters)."""
        naive = datetime.now()
        aware = datetime.now(UTC)
        with pytest.raises(TypeError):
            _ = aware - naive

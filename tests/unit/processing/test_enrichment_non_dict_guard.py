"""Tests for the non-dict item guard in EnrichmentPipeline.enrich()."""

from unittest.mock import MagicMock, patch

from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus


def _make_context(**kwargs: object) -> ProcessingContext:
    ctx = MagicMock(spec=ProcessingContext)
    ctx.action_name = kwargs.get("action_name", "test_action")
    ctx.action_config = kwargs.get("action_config", MagicMock())
    ctx.source_data = kwargs.get("source_data", [])
    ctx.parent_records = kwargs.get("parent_records", [])
    return ctx


def _make_result(
    data: list, status: ProcessingStatus = ProcessingStatus.SUCCESS
) -> ProcessingResult:
    result = MagicMock(spec=ProcessingResult)
    result.data = data
    result.status = status
    result.error = None
    return result


class TestNonDictEnrichmentGuard:
    """Guard at top of EnrichmentPipeline.enrich() filters non-dict items."""

    def test_all_dicts_pass_through_unchanged(self):
        pipeline = EnrichmentPipeline(enrichers=[])
        result = _make_result([{"a": 1}, {"b": 2}, {"c": 3}])
        context = _make_context()

        with patch("agent_actions.processing.enrichment.fire_event"):
            enriched = pipeline.enrich(result, context)

        assert enriched.data == [{"a": 1}, {"b": 2}, {"c": 3}]
        assert enriched.status == ProcessingStatus.SUCCESS

    def test_mixed_types_filters_all_non_dict(self):
        """str, int, list, None, bool are all filtered; dicts survive."""
        pipeline = EnrichmentPipeline(enrichers=[])
        result = _make_result([{"valid": True}, "string", 42, None, ["a", "list"], True])
        context = _make_context()

        with patch("agent_actions.processing.enrichment.fire_event"):
            enriched = pipeline.enrich(result, context)

        assert enriched.data == [{"valid": True}]
        assert enriched.status == ProcessingStatus.SUCCESS

    def test_all_non_dict_marks_failed_with_error(self):
        pipeline = EnrichmentPipeline(enrichers=[])
        result = _make_result(["string1", "string2", 99])
        context = _make_context(action_name="classify")

        with patch("agent_actions.processing.enrichment.fire_event"):
            enriched = pipeline.enrich(result, context)

        assert enriched.data == []
        assert enriched.status == ProcessingStatus.FAILED
        assert enriched.error == (
            "All 3 items in result.data were non-dict (action=classify) — enrichment skipped"
        )

    def test_all_non_dict_returns_early(self):
        """When all items are non-dict, enrichers are not invoked."""
        mock_enricher = MagicMock()
        pipeline = EnrichmentPipeline(enrichers=[mock_enricher])
        result = _make_result(["bad1", "bad2"])
        context = _make_context()

        with patch("agent_actions.processing.enrichment.fire_event"):
            pipeline.enrich(result, context)

        mock_enricher.enrich.assert_not_called()

    def test_warning_logged_on_filter(self):
        pipeline = EnrichmentPipeline(enrichers=[])
        result = _make_result([{"ok": 1}, "bad1", 42])
        context = _make_context(action_name="enrich_test")

        with (
            patch("agent_actions.processing.enrichment.logger") as mock_logger,
            patch("agent_actions.processing.enrichment.fire_event"),
        ):
            pipeline.enrich(result, context)

        mock_logger.warning.assert_called_once()
        args = mock_logger.warning.call_args.args
        assert args[1] == 2  # invalid_count
        assert args[2] == "enrich_test"  # action_name

    def test_empty_data_no_filtering(self):
        pipeline = EnrichmentPipeline(enrichers=[])
        result = _make_result([])
        context = _make_context()

        with patch("agent_actions.processing.enrichment.fire_event"):
            enriched = pipeline.enrich(result, context)

        assert enriched.data == []
        assert enriched.status == ProcessingStatus.SUCCESS

    def test_enrichers_only_see_dict_items(self):
        mock_enricher = MagicMock()
        mock_enricher.__class__.__name__ = "MockEnricher"

        def verify_all_dicts(result, context):
            for item in result.data:
                item.get("target_id")  # would crash on non-dict
            return result

        mock_enricher.enrich.side_effect = verify_all_dicts

        pipeline = EnrichmentPipeline(enrichers=[mock_enricher])
        result = _make_result([{"id": 1}, "crash_me", None, {"id": 2}])
        context = _make_context()

        with patch("agent_actions.processing.enrichment.fire_event"):
            enriched = pipeline.enrich(result, context)

        mock_enricher.enrich.assert_called_once()
        assert enriched.data == [{"id": 1}, {"id": 2}]

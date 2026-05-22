"""Regression tests for F1: prefilter guard-filtered records must write DISPOSITION_FILTERED.

The bug: prefilter_by_guard() dropped filtered records entirely. The caller
(_guard_filter / _guard_filter_file_mode) could only count them by subtraction
and created ProcessingResult.filtered(source_guid=None). result_collector.py
skips disposition writes when source_guid is None, so filtered records vanished
from the DB.

The fix: prefilter_by_guard() now returns filtered records as a 4th return
value. The callers iterate them to create ProcessingResult.filtered() with
each record's actual source_guid, enabling proper disposition writes.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.input.preprocessing.filtering.evaluator import GuardResult
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.storage.backend import DISPOSITION_FILTERED
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard
from tests.conftest import wire_batch_disposition_delegate


def _make_evaluator(pass_fn):
    """Create a mock evaluator whose evaluate delegates to pass_fn."""
    evaluator = MagicMock()

    def side_effect(*, item, guard_config, context=None, conditional_clause=None):
        if pass_fn(item):
            return GuardResult.passed()
        return GuardResult.filtered()

    evaluator.evaluate.side_effect = side_effect
    return evaluator


def _make_context(
    agent_name: str = "test_action",
    *,
    guard: dict | None = None,
    storage_backend: Any = None,
) -> ProcessingContext:
    config: dict[str, Any] = {"agent_type": agent_name, "name": agent_name}
    if guard is not None:
        config["guard"] = guard
    return ProcessingContext(
        agent_config=config,
        agent_name=agent_name,
        storage_backend=storage_backend,
    )


# ---------------------------------------------------------------------------
# prefilter_by_guard returns filtered records with identity
# ---------------------------------------------------------------------------


class TestPrefilterReturnsFilteredRecords:
    """prefilter_by_guard must return filtered records so callers can
    create ProcessingResult.filtered() with proper source_guid."""

    def test_filtered_records_returned_with_source_guid(self):
        """Filtered records appear in the 4th return value."""
        data = [
            {"content": {"score": 90}, "source_guid": "sg-pass"},
            {"content": {"score": 40}, "source_guid": "sg-filter-1"},
            {"content": {"score": 30}, "source_guid": "sg-filter-2"},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing, filtered = prefilter_by_guard(data, config, "test")

        assert len(passing) == 1
        assert len(filtered) == 2
        assert filtered[0]["source_guid"] == "sg-filter-1"
        assert filtered[1]["source_guid"] == "sg-filter-2"

    def test_no_guard_returns_empty_filtered(self):
        """No guard config -> filtered list is empty."""
        data = [{"content": {"x": 1}}]
        _, _, _, filtered = prefilter_by_guard(data, {}, "test")
        assert filtered == []

    def test_all_pass_returns_empty_filtered(self):
        """All records pass -> filtered list is empty."""
        data = [{"content": {"score": 90}}, {"content": {"score": 95}}]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            _, _, _, filtered = prefilter_by_guard(data, config, "test")

        assert filtered == []

    def test_all_filtered_returns_all(self):
        """All records fail filter -> all in filtered list."""
        data = [
            {"content": {"score": 10}, "source_guid": "sg-1"},
            {"content": {"score": 20}, "source_guid": "sg-2"},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, _, _, filtered = prefilter_by_guard(data, config, "test")

        assert passing == []
        assert len(filtered) == 2

    def test_filtered_uses_original_data_when_provided(self):
        """With original_data, filtered list contains originals (not observe-filtered)."""
        data = [{"content": {"score": 40}}]
        raw = [{"content": {"score": 40, "name": "Bob"}, "source_guid": "sg-2"}]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            _, _, _, filtered = prefilter_by_guard(data, config, "test", original_data=raw)

        assert len(filtered) == 1
        assert filtered[0]["source_guid"] == "sg-2"
        assert filtered[0]["content"]["name"] == "Bob"


# ---------------------------------------------------------------------------
# _guard_filter produces FILTERED results with source_guid
# ---------------------------------------------------------------------------


class TestGuardFilterDisposition:
    """_guard_filter must produce ProcessingResult.filtered() with the
    record's actual source_guid so result_collector writes DISPOSITION_FILTERED."""

    def test_filtered_result_has_source_guid(self):
        """RECORD-mode: filtered ProcessingResult carries the record's source_guid."""
        records = [
            {"content": {"score": 90}, "source_guid": "sg-pass"},
            {"content": {"score": 40}, "source_guid": "sg-filter"},
        ]
        context = _make_context(guard={"clause": "score >= 80", "behavior": "filter"})
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            processor = UnifiedProcessor()
            passing, guard_results = processor._guard_filter(records, context)

        assert len(passing) == 1
        assert len(guard_results) == 1
        assert guard_results[0].status == ProcessingStatus.FILTERED
        assert guard_results[0].source_guid == "sg-filter"

    def test_multiple_filtered_records_have_distinct_guids(self):
        """Each filtered record gets its own source_guid on the result."""
        records = [
            {"content": {"score": 10}, "source_guid": "sg-1"},
            {"content": {"score": 20}, "source_guid": "sg-2"},
            {"content": {"score": 30}, "source_guid": "sg-3"},
        ]
        context = _make_context(guard={"clause": "score >= 80", "behavior": "filter"})
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            processor = UnifiedProcessor()
            passing, guard_results = processor._guard_filter(records, context)

        assert passing == []
        assert len(guard_results) == 3
        guids = [r.source_guid for r in guard_results]
        assert guids == ["sg-1", "sg-2", "sg-3"]

    def test_filtered_without_source_guid_gets_none(self):
        """Record without source_guid -> result.source_guid is None (no crash)."""
        records = [{"content": {"score": 40}}]
        context = _make_context(guard={"clause": "score >= 80", "behavior": "filter"})
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            processor = UnifiedProcessor()
            _, guard_results = processor._guard_filter(records, context)

        assert len(guard_results) == 1
        assert guard_results[0].source_guid is None


# ---------------------------------------------------------------------------
# _guard_filter_file_mode produces FILTERED results with source_guid
# ---------------------------------------------------------------------------


class TestGuardFilterFileModeDisposition:
    """FILE-mode: _guard_filter_file_mode must also produce FILTERED results
    with proper source_guid."""

    def test_filtered_result_has_source_guid_file_mode(self):
        """FILE-mode: filtered result carries source_guid from original_data."""
        data = [{"content": {"score": 40}}]
        raw = [{"content": {"score": 40, "name": "Bob"}, "source_guid": "sg-filter"}]
        context = ProcessingContext(
            agent_config={"guard": {"clause": "score >= 80", "behavior": "filter"}},
            agent_name="test",
        )
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            processor = UnifiedProcessor()
            passing, guard_results, original_passing = processor._guard_filter_file_mode(
                data, context, raw
            )

        assert passing == []
        assert len(guard_results) == 1
        assert guard_results[0].status == ProcessingStatus.FILTERED
        assert guard_results[0].source_guid == "sg-filter"


# ---------------------------------------------------------------------------
# End-to-end: DISPOSITION_FILTERED written to storage backend
# ---------------------------------------------------------------------------


class TestFilteredDispositionWritten:
    """Integration: when a prefilter-filtered record has source_guid,
    result_collector must call set_disposition(DISPOSITION_FILTERED)."""

    def test_record_mode_filtered_writes_disposition(self):
        """RECORD mode: filtered record -> DISPOSITION_FILTERED in DB."""
        records = [
            {"content": {"score": 90}, "source_guid": "sg-pass"},
            {"content": {"score": 40}, "source_guid": "sg-filter"},
        ]
        mock_backend = MagicMock()
        wire_batch_disposition_delegate(mock_backend)
        context = _make_context(
            guard={"clause": "score >= 80", "behavior": "filter"},
            storage_backend=mock_backend,
        )
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        class PassthroughStrategy:
            def invoke(self, recs, ctx):
                return [
                    ProcessingResult.success(
                        data=[{"content": {"test_action": {"out": 1}}}],
                        source_guid=r["source_guid"],
                    )
                    for r in recs
                ]

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            output, stats = UnifiedProcessor().process(records, context, PassthroughStrategy())

        assert stats.filtered == 1
        assert stats.success == 1

        # Verify DISPOSITION_FILTERED was written with the correct source_guid
        disposition_calls = [
            c
            for c in mock_backend.set_disposition.call_args_list
            if len(c.args) >= 3 and c.args[2] == DISPOSITION_FILTERED
        ]
        assert len(disposition_calls) == 1
        assert disposition_calls[0].args[1] == "sg-filter"

    def test_file_mode_filtered_writes_disposition(self):
        """FILE mode: filtered record -> DISPOSITION_FILTERED in DB."""
        records = [
            {"content": {"score": 90}, "source_guid": "sg-pass"},
            {"content": {"score": 40}, "source_guid": "sg-filter"},
        ]
        raw = records
        mock_backend = MagicMock()
        wire_batch_disposition_delegate(mock_backend)
        context = _make_context(
            guard={"clause": "score >= 80", "behavior": "filter"},
            storage_backend=mock_backend,
        )
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        class PassthroughStrategy:
            def invoke(self, recs, ctx):
                return [
                    ProcessingResult.success(
                        data=[{"content": {"test_action": {"out": 1}}}],
                        source_guid=r["source_guid"],
                    )
                    for r in recs
                ]

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            output, stats = UnifiedProcessor().process(
                records, context, PassthroughStrategy(), raw_records=raw
            )

        assert stats.filtered == 1

        disposition_calls = [
            c
            for c in mock_backend.set_disposition.call_args_list
            if len(c.args) >= 3 and c.args[2] == DISPOSITION_FILTERED
        ]
        assert len(disposition_calls) == 1
        assert disposition_calls[0].args[1] == "sg-filter"

    def test_no_source_guid_no_disposition_write(self):
        """Record without source_guid -> no disposition write (no crash)."""
        records = [{"content": {"score": 40}}]
        mock_backend = MagicMock()
        wire_batch_disposition_delegate(mock_backend)
        context = _make_context(
            guard={"clause": "score >= 80", "behavior": "filter"},
            storage_backend=mock_backend,
        )
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        class NoOpStrategy:
            def invoke(self, recs, ctx):
                return []

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            output, stats = UnifiedProcessor().process(records, context, NoOpStrategy())

        assert stats.filtered == 1
        # No disposition write because source_guid is missing
        disposition_calls = [
            c
            for c in mock_backend.set_disposition.call_args_list
            if len(c.args) >= 3 and c.args[2] == DISPOSITION_FILTERED
        ]
        assert len(disposition_calls) == 0

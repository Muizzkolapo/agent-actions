"""Tests for FILE-mode guard pre-filter."""

from unittest.mock import MagicMock, patch

from agent_actions.input.preprocessing.filtering.evaluator import GuardResult
from agent_actions.processing.types import ProcessingStatus
from agent_actions.workflow.pipeline import _build_skipped_results
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard


def _make_evaluator(pass_fn):
    """Create a mock evaluator whose evaluate delegates to pass_fn.

    pass_fn receives the eval_item dict and returns True if the item should pass.
    """
    evaluator = MagicMock()

    def side_effect(*, item, guard_config, context=None, conditional_clause=None):
        if pass_fn(item):
            return GuardResult.passed()
        return GuardResult.filtered()

    evaluator.evaluate.side_effect = side_effect
    return evaluator


class TestPrefilterByGuard:
    """Tests for prefilter_by_guard()."""

    def test_no_guard_returns_all(self):
        """No guard config -> all records pass, no skipped."""
        data = [{"content": {"x": 1}}, {"content": {"x": 2}}]
        passing, skipped, original_passing = prefilter_by_guard(data, {}, "test")
        assert passing == data
        assert skipped == []
        assert original_passing == data

    def test_no_guard_with_original_data(self):
        """No guard config with original_data -> original_passing is original_data."""
        data = [{"content": {"x": 1}}]
        raw = [{"content": {"x": 1}, "extra_field": "preserved"}]
        passing, skipped, original_passing = prefilter_by_guard(data, {}, "test", original_data=raw)
        assert passing == data
        assert original_passing == raw

    def test_filter_removes_failing_records(self):
        """behavior: filter -> failing records excluded from both lists."""
        data = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
            {"content": {"score": 85}},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 2
        assert passing[0]["content"]["score"] == 90
        assert passing[1]["content"]["score"] == 85
        assert skipped == []
        assert original_passing == passing

    def test_skip_preserves_failing_records(self):
        """behavior: skip -> failing records in skipped list."""
        data = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
            {"content": {"score": 85}},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "skip"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 2
        assert len(skipped) == 1
        assert skipped[0]["content"]["score"] == 40

    def test_all_pass(self):
        """All records pass guard -> all in passing, none skipped."""
        data = [{"content": {"score": 90}}, {"content": {"score": 95}}]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 2
        assert skipped == []

    def test_all_filtered(self):
        """All records fail with filter -> both lists empty."""
        data = [{"content": {"score": 10}}, {"content": {"score": 20}}]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert passing == []
        assert skipped == []
        assert original_passing == []

    def test_all_skipped(self):
        """All records fail with skip -> all in skipped."""
        data = [{"content": {"score": 10}}, {"content": {"score": 20}}]
        config = {"guard": {"clause": "score >= 80", "behavior": "skip"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert passing == []
        assert len(skipped) == 2
        assert original_passing == []

    def test_does_not_mutate_input(self):
        """Pre-filter must not mutate the input list."""
        data = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
        ]
        original_len = len(data)
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            prefilter_by_guard(data, config, "test")

        assert len(data) == original_len

    def test_default_behavior_is_filter(self):
        """When behavior is not specified, default is filter."""
        data = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
        ]
        config = {"guard": {"clause": "score >= 80"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 1
        assert skipped == []

    # -- original_data preservation tests --

    def test_original_data_preserves_pre_observe_fields(self):
        """original_passing returns items from original_data, not from data."""
        # Simulate observe-filtered data (fewer fields) vs raw data (all fields)
        filtered = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
            {"content": {"score": 85}},
        ]
        raw = [
            {"content": {"score": 90, "name": "Alice"}, "source_guid": "sg-1"},
            {"content": {"score": 40, "name": "Bob"}, "source_guid": "sg-2"},
            {"content": {"score": 85, "name": "Carol"}, "source_guid": "sg-3"},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(
                filtered, config, "test", original_data=raw
            )

        # passing has observe-filtered items
        assert len(passing) == 2
        assert "name" not in passing[0]["content"]

        # original_passing has the raw items with all fields preserved
        assert len(original_passing) == 2
        assert original_passing[0]["content"]["name"] == "Alice"
        assert original_passing[0]["source_guid"] == "sg-1"
        assert original_passing[1]["content"]["name"] == "Carol"
        assert original_passing[1]["source_guid"] == "sg-3"

    def test_original_data_with_skip_behavior(self):
        """original_passing only includes passing items, not skipped."""
        filtered = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
        ]
        raw = [
            {"content": {"score": 90, "name": "Alice"}, "source_guid": "sg-1"},
            {"content": {"score": 40, "name": "Bob"}, "source_guid": "sg-2"},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "skip"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(
                filtered, config, "test", original_data=raw
            )

        assert len(passing) == 1
        assert len(skipped) == 1
        assert len(original_passing) == 1
        assert original_passing[0]["content"]["name"] == "Alice"

    # -- Edge case tests --

    def test_empty_data(self):
        """Empty data list -> all empty results."""
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: True)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard([], config, "test")

        assert passing == []
        assert skipped == []
        assert original_passing == []

    def test_non_dict_content(self):
        """Non-dict content wraps as {_raw: content} for evaluation."""
        data = [{"content": "plain-text-value"}]
        config = {"guard": {"clause": "always_true", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: "_raw" in item)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 1
        assert passing[0]["content"] == "plain-text-value"

    def test_missing_content_key(self):
        """Item without content key -> item itself used as eval_item."""
        data = [{"score": 90, "name": "Alice"}]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 1


class TestBuildSkippedResults:
    """Tests for _build_skipped_results()."""

    def test_empty_list(self):
        """Empty skipped list -> empty results."""
        results = _build_skipped_results([])
        assert results == []

    def test_creates_unprocessed_results(self):
        """Each skipped item becomes an UNPROCESSED result."""
        skipped = [
            {"content": {"score": 40}, "source_guid": "sg-1"},
            {"content": {"score": 20}, "source_guid": "sg-2"},
        ]
        results = _build_skipped_results(skipped)

        assert len(results) == 2
        for i, result in enumerate(results):
            assert result.status == ProcessingStatus.UNPROCESSED
            assert result.data == [skipped[i]]
            assert result.source_guid == skipped[i]["source_guid"]

    def test_missing_source_guid(self):
        """Items without source_guid get None."""
        skipped = [{"content": {"score": 40}}]
        results = _build_skipped_results(skipped)

        assert len(results) == 1
        assert results[0].source_guid is None
        assert results[0].status == ProcessingStatus.UNPROCESSED

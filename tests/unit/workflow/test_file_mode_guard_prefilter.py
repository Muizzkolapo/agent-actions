"""Tests for FILE-mode guard pre-filter."""

from unittest.mock import MagicMock, patch

from agent_actions.input.preprocessing.filtering.evaluator import GuardResult
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard


def _make_evaluator(pass_fn):
    """Create a mock evaluator whose evaluate_with_context delegates to pass_fn.

    pass_fn receives the eval_item dict and returns True if the item should pass.
    """
    evaluator = MagicMock()

    def side_effect(*, item, guard_config, context, conditional_clause):
        if pass_fn(item):
            return GuardResult.passed()
        return GuardResult.filtered()

    evaluator.evaluate_with_context.side_effect = side_effect
    return evaluator


class TestPrefilterByGuard:
    """Tests for prefilter_by_guard()."""

    def test_no_guard_returns_all(self):
        """No guard config -> all records pass, no skipped."""
        data = [{"content": {"x": 1}}, {"content": {"x": 2}}]
        passing, skipped = prefilter_by_guard(data, {}, "test")
        assert passing == data
        assert skipped == []

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
            passing, skipped = prefilter_by_guard(data, config, "test")

        assert len(passing) == 2
        assert passing[0]["content"]["score"] == 90
        assert passing[1]["content"]["score"] == 85
        assert skipped == []

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
            passing, skipped = prefilter_by_guard(data, config, "test")

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
            passing, skipped = prefilter_by_guard(data, config, "test")

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
            passing, skipped = prefilter_by_guard(data, config, "test")

        assert passing == []
        assert skipped == []

    def test_all_skipped(self):
        """All records fail with skip -> all in skipped."""
        data = [{"content": {"score": 10}}, {"content": {"score": 20}}]
        config = {"guard": {"clause": "score >= 80", "behavior": "skip"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped = prefilter_by_guard(data, config, "test")

        assert passing == []
        assert len(skipped) == 2

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
            passing, skipped = prefilter_by_guard(data, config, "test")

        assert len(passing) == 1
        assert skipped == []

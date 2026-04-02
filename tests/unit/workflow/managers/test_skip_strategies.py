"""Tests for skip condition strategies and SkipEvaluator orchestrator."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.managers.skip import (
    GuardStrategy,
    LegacySkipIfStrategy,
    SkipConditionStrategy,
    SkipEvaluator,
)

GUARD_FILTER_PATH = "agent_actions.workflow.managers.skip.get_global_guard_filter"
FIRE_EVENT_PATH = "agent_actions.workflow.managers.skip.fire_event"


@dataclass
class FakeFilterResult:
    """Minimal stand-in for FilterResult."""

    success: bool
    matched: bool = False
    error: str | None = None


def _make_filter(result: FakeFilterResult):
    """Return a mock GuardFilter whose filter_item returns *result*."""
    svc = MagicMock()
    svc.filter_item.return_value = result
    return svc


# ── SkipConditionStrategy ──────────────────────────────────────────────


class TestSkipConditionStrategy:
    """Tests for SkipConditionStrategy (inverse logic: skip when NOT matched)."""

    @pytest.fixture
    def strategy(self):
        return SkipConditionStrategy()

    def test_no_condition_returns_false(self, strategy):
        assert strategy.should_skip({}, {}) is False

    def test_dict_where_matched_does_not_skip(self, strategy):
        """When filter matches, the condition is met → do NOT skip."""
        filt = _make_filter(FakeFilterResult(success=True, matched=True))
        with patch(GUARD_FILTER_PATH, return_value=filt):
            result = strategy.should_skip(
                {"skip_condition": {"where": "x > 1"}, "agent_type": "a"}, {}
            )
        assert result is False

    def test_dict_where_not_matched_skips(self, strategy):
        """When filter does not match, inverse logic → skip and fire AgentSkipEvent."""
        filt = _make_filter(FakeFilterResult(success=True, matched=False))
        with patch(GUARD_FILTER_PATH, return_value=filt), patch(FIRE_EVENT_PATH) as mock_fire:
            result = strategy.should_skip(
                {"skip_condition": {"where": "x > 1"}, "agent_type": "a"}, {}
            )
        assert result is True
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert event.action_name == "a"
        assert "skip_condition" in event.skip_reason

    def test_string_form(self, strategy):
        """String skip_condition should be accepted as where clause."""
        filt = _make_filter(FakeFilterResult(success=True, matched=False))
        with patch(GUARD_FILTER_PATH, return_value=filt), patch(FIRE_EVENT_PATH) as mock_fire:
            result = strategy.should_skip({"skip_condition": "x > 1", "agent_type": "a"}, {})
        assert result is True
        mock_fire.assert_called_once()

    def test_filter_failure_returns_false(self, strategy):
        """When filter evaluation fails, fail-open (don't skip)."""
        filt = _make_filter(FakeFilterResult(success=False, error="parse error"))
        with patch(GUARD_FILTER_PATH, return_value=filt):
            result = strategy.should_skip(
                {"skip_condition": {"where": "bad"}, "agent_type": "a"}, {}
            )
        assert result is False

    def test_exception_returns_false(self, strategy):
        """Exception in evaluation should fail-open."""
        filt = MagicMock()
        filt.filter_item.side_effect = ValueError("boom")
        with patch(GUARD_FILTER_PATH, return_value=filt):
            result = strategy.should_skip({"skip_condition": {"where": "x"}, "agent_type": "a"}, {})
        assert result is False

    def test_empty_where_clause_returns_false(self, strategy):
        """Dict without 'where' key should not skip."""
        result = strategy.should_skip({"skip_condition": {"other": "stuff"}, "agent_type": "a"}, {})
        assert result is False


# ── GuardStrategy ──────────────────────────────────────────────────────


class TestGuardStrategy:
    """Tests for GuardStrategy (guard with scope='action')."""

    @pytest.fixture
    def strategy(self):
        return GuardStrategy()

    def test_no_guard_returns_false(self, strategy):
        assert strategy.should_skip({}, {}) is False

    def test_scope_not_agent_returns_false(self, strategy):
        cfg = {"guard": {"scope": "workflow", "clause": "x > 1"}}
        assert strategy.should_skip(cfg, {}) is False

    def test_matched_does_not_skip(self, strategy):
        """Guard matched → agent proceeds."""
        filt = _make_filter(FakeFilterResult(success=True, matched=True))
        cfg = {"guard": {"scope": "action", "clause": "x > 1"}, "agent_type": "a"}
        with patch(GUARD_FILTER_PATH, return_value=filt):
            assert strategy.should_skip(cfg, {}) is False

    def test_not_matched_skips(self, strategy):
        """Guard not matched → skip agent and fire AgentSkipEvent."""
        filt = _make_filter(FakeFilterResult(success=True, matched=False))
        cfg = {"guard": {"scope": "action", "clause": "x > 1"}, "agent_type": "a"}
        with patch(GUARD_FILTER_PATH, return_value=filt), patch(FIRE_EVENT_PATH) as mock_fire:
            assert strategy.should_skip(cfg, {}) is True
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert event.action_name == "a"
        assert "guard" in event.skip_reason

    def test_filter_error_passthrough_true(self, strategy):
        """Error with passthrough_on_error=True → don't skip."""
        filt = _make_filter(FakeFilterResult(success=False, error="oops"))
        cfg = {
            "guard": {"scope": "action", "clause": "x", "passthrough_on_error": True},
            "agent_type": "a",
        }
        with patch(GUARD_FILTER_PATH, return_value=filt):
            assert strategy.should_skip(cfg, {}) is False

    def test_filter_error_passthrough_false(self, strategy):
        """Error with passthrough_on_error=False → skip and fire event."""
        filt = _make_filter(FakeFilterResult(success=False, error="oops"))
        cfg = {
            "guard": {"scope": "action", "clause": "x", "passthrough_on_error": False},
            "agent_type": "a",
        }
        with patch(GUARD_FILTER_PATH, return_value=filt), patch(FIRE_EVENT_PATH) as mock_fire:
            assert strategy.should_skip(cfg, {}) is True
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert event.action_name == "a"
        assert "passthrough_on_error" in event.skip_reason

    def test_exception_passthrough_true(self, strategy):
        """Exception with passthrough_on_error=True → don't skip."""
        filt = MagicMock()
        filt.filter_item.side_effect = ValueError("boom")
        cfg = {
            "guard": {"scope": "action", "clause": "x", "passthrough_on_error": True},
            "agent_type": "a",
        }
        with patch(GUARD_FILTER_PATH, return_value=filt):
            assert strategy.should_skip(cfg, {}) is False

    def test_exception_passthrough_false(self, strategy):
        """Exception with passthrough_on_error=False → skip."""
        filt = MagicMock()
        filt.filter_item.side_effect = TypeError("boom")
        cfg = {
            "guard": {"scope": "action", "clause": "x", "passthrough_on_error": False},
            "agent_type": "a",
        }
        with patch(GUARD_FILTER_PATH, return_value=filt), patch(FIRE_EVENT_PATH):
            assert strategy.should_skip(cfg, {}) is True

    def test_context_excludes_guard_key(self, strategy):
        """Context passed to filter should not include the 'guard' key itself."""
        filt = _make_filter(FakeFilterResult(success=True, matched=True))
        cfg = {
            "guard": {"scope": "action", "clause": "x > 1"},
            "agent_type": "a",
            "dependencies": ["b"],
        }
        with patch(GUARD_FILTER_PATH, return_value=filt):
            strategy.should_skip(cfg, {"prev": "data"})

        call_args = filt.filter_item.call_args[0][0]
        assert "guard" not in call_args.data.get("agent_config", {})

    def test_flattens_previous_outputs_to_top_level(self, strategy):
        """Action outputs from previous_outputs are accessible as top-level keys."""
        filt = _make_filter(FakeFilterResult(success=True, matched=True))
        cfg = {
            "guard": {"scope": "action", "clause": "x > 1"},
            "agent_type": "a",
        }
        previous_outputs = {
            "classify": [{"category": "bug"}],
            "classify_meta": {"status": "completed"},
        }
        with patch(GUARD_FILTER_PATH, return_value=filt):
            strategy.should_skip(cfg, previous_outputs)

        call_args = filt.filter_item.call_args[0][0]
        # Action outputs should be flattened to top-level
        assert "classify" in call_args.data
        assert "classify_meta" in call_args.data
        # previous_outputs should still be present for backward compat
        assert "previous_outputs" in call_args.data

    def test_unwraps_single_item_lists(self, strategy):
        """Single-item list outputs are unwrapped to their dict for dot notation."""
        filt = _make_filter(FakeFilterResult(success=True, matched=True))
        cfg = {
            "guard": {"scope": "action", "clause": "x > 1"},
            "agent_type": "a",
        }
        previous_outputs = {
            "assess": [{"severity": "high"}],
        }
        with patch(GUARD_FILTER_PATH, return_value=filt):
            strategy.should_skip(cfg, previous_outputs)

        call_args = filt.filter_item.call_args[0][0]
        # Single-item list should be unwrapped to dict
        assert call_args.data["assess"] == {"severity": "high"}

    def test_multi_item_lists_not_unwrapped(self, strategy):
        """Multi-item list outputs are kept as lists."""
        filt = _make_filter(FakeFilterResult(success=True, matched=True))
        cfg = {
            "guard": {"scope": "action", "clause": "x > 1"},
            "agent_type": "a",
        }
        previous_outputs = {
            "extract": [{"id": 1}, {"id": 2}],
        }
        with patch(GUARD_FILTER_PATH, return_value=filt):
            strategy.should_skip(cfg, previous_outputs)

        call_args = filt.filter_item.call_args[0][0]
        # Multi-item list should remain as-is
        assert call_args.data["extract"] == [{"id": 1}, {"id": 2}]


# ── LegacySkipIfStrategy ──────────────────────────────────────────────


class TestLegacySkipIfStrategy:
    """Tests for LegacySkipIfStrategy (direct logic: matched → skip)."""

    @pytest.fixture
    def strategy(self):
        return LegacySkipIfStrategy()

    def test_no_skip_if_returns_false(self, strategy):
        assert strategy.should_skip({}, {}) is False

    def test_matched_skips(self, strategy):
        """When filter matches, skip (direct logic) and fire AgentSkipEvent."""
        filt = _make_filter(FakeFilterResult(success=True, matched=True))
        with patch(GUARD_FILTER_PATH, return_value=filt), patch(FIRE_EVENT_PATH) as mock_fire:
            result = strategy.should_skip({"skip_if": "x > 1", "agent_type": "a"}, {})
        assert result is True
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert event.action_name == "a"
        assert "skip_if" in event.skip_reason

    def test_not_matched_does_not_skip(self, strategy):
        filt = _make_filter(FakeFilterResult(success=True, matched=False))
        with patch(GUARD_FILTER_PATH, return_value=filt):
            result = strategy.should_skip({"skip_if": "x > 1", "agent_type": "a"}, {})
        assert result is False

    def test_filter_failure_returns_false(self, strategy):
        """When filter evaluation fails (success=False), fail-open (don't skip)."""
        filt = _make_filter(FakeFilterResult(success=False, error="parse error"))
        with patch(GUARD_FILTER_PATH, return_value=filt):
            result = strategy.should_skip({"skip_if": "bad expr", "agent_type": "a"}, {})
        assert result is False

    def test_exception_returns_false(self, strategy):
        filt = MagicMock()
        filt.filter_item.side_effect = ValueError("boom")
        with patch(GUARD_FILTER_PATH, return_value=filt):
            result = strategy.should_skip({"skip_if": "x > 1", "agent_type": "a"}, {})
        assert result is False


# ── SkipEvaluator ──────────────────────────────────────────────────────


class TestSkipEvaluator:
    """Tests for SkipEvaluator orchestrator."""

    def test_no_conditions_returns_false(self):
        evaluator = SkipEvaluator()
        # No skip_condition, guard, or skip_if → not skipped
        with patch(GUARD_FILTER_PATH, return_value=MagicMock()):
            assert evaluator.should_skip_action({"agent_type": "a"}) is False

    def test_first_match_short_circuits(self):
        """If SkipConditionStrategy says skip, later strategies are not called."""
        evaluator = SkipEvaluator()
        filt = _make_filter(FakeFilterResult(success=True, matched=False))
        cfg = {"skip_condition": {"where": "x > 1"}, "agent_type": "a"}
        with patch(GUARD_FILTER_PATH, return_value=filt), patch(FIRE_EVENT_PATH):
            result = evaluator.should_skip_action(cfg, {})
        assert result is True

    def test_strategy_exception_continues(self):
        """If one strategy raises, evaluator continues to the next."""
        evaluator = SkipEvaluator()
        # Make first strategy raise, but set up config for legacy to match
        evaluator.strategies[0] = MagicMock()
        evaluator.strategies[0].should_skip.side_effect = ValueError("first broke")
        evaluator.strategies[0].get_strategy_name.return_value = "broken"

        evaluator.strategies[1] = MagicMock()
        evaluator.strategies[1].should_skip.return_value = False
        evaluator.strategies[1].get_strategy_name.return_value = "guard"

        evaluator.strategies[2] = MagicMock()
        evaluator.strategies[2].should_skip.return_value = True
        evaluator.strategies[2].get_strategy_name.return_value = "skip_if"

        result = evaluator.should_skip_action({"agent_type": "a"}, {})
        assert result is True

    def test_none_previous_outputs_normalized_to_empty_dict(self):
        """None previous_outputs should be treated as empty dict."""
        evaluator = SkipEvaluator()
        with patch(GUARD_FILTER_PATH, return_value=MagicMock()):
            # Should not raise — None is handled
            evaluator.should_skip_action({"agent_type": "a"}, None)

    def test_repr(self):
        evaluator = SkipEvaluator()
        assert "3" in repr(evaluator)

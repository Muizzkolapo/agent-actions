"""Tests for skip condition strategies and SkipEvaluator orchestrator."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.managers.skip import SkipConditionStrategy, SkipEvaluator

GUARD_FILTER_PATH = "agent_actions.workflow.managers.skip.get_global_guard_filter"
FIRE_EVENT_PATH = "agent_actions.workflow.managers.skip.fire_event"


@dataclass
class FakeFilterResult:
    """Minimal stand-in for FilterResult."""

    success: bool
    matched: bool = False
    error: str | None = None
    error_category: object | None = None
    execution_time: float = 0.0


def _make_filter(result: FakeFilterResult):
    """Return a mock GuardFilter whose filter_item returns *result*."""
    svc = MagicMock()
    svc.filter_item.return_value = result
    return svc


def _raising_filter(exc: Exception):
    svc = MagicMock()
    svc.filter_item.side_effect = exc
    return svc


# ── SkipConditionStrategy ──────────────────────────────────────────────


class TestSkipConditionStrategy:
    """Tests for SkipConditionStrategy (inverse logic: skip when NOT matched)."""

    @pytest.fixture
    def strategy(self):
        return SkipConditionStrategy()

    def test_no_condition_returns_false(self, strategy):
        assert strategy.should_skip({}, {}) is False

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

    @pytest.mark.parametrize(
        ("filt", "where"),
        [
            pytest.param(
                _make_filter(FakeFilterResult(success=True, matched=True)),
                "x > 1",
                id="condition_matched",
            ),
            pytest.param(
                _make_filter(FakeFilterResult(success=False, error="parse error")),
                "bad",
                id="filter_failure_fails_open",
            ),
            pytest.param(_raising_filter(ValueError("boom")), "x", id="exception_fails_open"),
        ],
    )
    def test_does_not_skip(self, strategy, filt, where):
        with patch(GUARD_FILTER_PATH, return_value=filt):
            result = strategy.should_skip(
                {"skip_condition": {"where": where}, "agent_type": "a"}, {}
            )
        assert result is False

    def test_empty_where_clause_returns_false(self, strategy):
        """Dict without 'where' key should not skip."""
        result = strategy.should_skip({"skip_condition": {"other": "stuff"}, "agent_type": "a"}, {})
        assert result is False


# ── SkipEvaluator ──────────────────────────────────────────────────────


class TestSkipEvaluator:
    """Tests for SkipEvaluator orchestrator."""

    def test_no_conditions_returns_false(self):
        evaluator = SkipEvaluator()
        # No skip_condition or guard → not skipped
        with patch(GUARD_FILTER_PATH, return_value=MagicMock()):
            assert evaluator.should_skip_action({"agent_type": "a"}) is False

    def test_a_skip_condition_skips_the_action(self):
        evaluator = SkipEvaluator()
        filt = _make_filter(FakeFilterResult(success=True, matched=False))
        cfg = {"skip_condition": {"where": "x > 1"}, "agent_type": "a"}
        with patch(GUARD_FILTER_PATH, return_value=filt), patch(FIRE_EVENT_PATH):
            result = evaluator.should_skip_action(cfg, {})
        assert result is True

    def test_strategy_exception_continues(self):
        """If one strategy raises, evaluator continues to the next."""
        evaluator = SkipEvaluator()
        broken = MagicMock()
        broken.should_skip.side_effect = ValueError("first broke")
        broken.get_strategy_name.return_value = "broken"
        working = MagicMock()
        working.should_skip.return_value = True
        working.get_strategy_name.return_value = "working"
        evaluator.strategies = [broken, working]

        result = evaluator.should_skip_action({"agent_type": "a"}, {})
        assert result is True
        working.should_skip.assert_called_once()

    def test_repr(self):
        evaluator = SkipEvaluator()
        assert repr(evaluator) == "SkipEvaluator(strategies=1)"

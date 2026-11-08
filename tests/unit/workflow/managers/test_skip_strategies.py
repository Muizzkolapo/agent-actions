"""Tests for the SkipEvaluator orchestrator.

No strategy is registered since skip_condition was retired (1701): a guard skips records.
"""

from unittest.mock import MagicMock

from agent_actions.workflow.managers.skip import SkipEvaluator


class TestSkipEvaluator:
    def test_nothing_skips_an_action(self):
        evaluator = SkipEvaluator()

        assert evaluator.should_skip_action({"agent_type": "a"}, {}) is False

    def test_a_retired_skip_condition_left_on_a_config_skips_nothing(self):
        cfg = {"agent_type": "a", "skip_condition": {"where": "x > 1"}}

        assert SkipEvaluator().should_skip_action(cfg, {}) is False

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
        assert repr(SkipEvaluator()) == "SkipEvaluator(strategies=0)"

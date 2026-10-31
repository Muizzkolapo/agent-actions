"""A guard error swallowed under passthrough_on_error is logged."""

import logging
from unittest.mock import MagicMock

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.input.preprocessing.filtering.guard_filter import GuardFilter

_EVALUATOR_LOGGER = "agent_actions.input.preprocessing.filtering.evaluator"


class TestPassthroughOnErrorLogging:
    """U-2.H: passthrough_on_error must log WARNING when exception is swallowed."""

    def test_passthrough_on_error_logs_debug_on_exception(self, caplog):
        """When guard raises and passthrough_on_error=True, DEBUG logged with context."""
        mock_filter = MagicMock(spec=GuardFilter)
        mock_filter.filter_item.side_effect = ValueError("bad expression")
        evaluator = GuardEvaluator(guard_filter=mock_filter)

        guard_config = {
            "clause": "some_field == true",
            "behavior": "filter",
            "passthrough_on_error": True,
        }

        with caplog.at_level(
            logging.DEBUG,
            logger=_EVALUATOR_LOGGER,
        ):
            result = evaluator.evaluate(
                item={"field": "value"},
                guard_config=guard_config,
            )

        assert result.should_execute is True

        passthrough_debugs = [
            r
            for r in caplog.records
            if r.levelname == "DEBUG" and "passthrough_on_error" in r.message
        ]
        assert len(passthrough_debugs) == 1, (
            "Must log exactly one DEBUG mentioning passthrough_on_error when exception is swallowed"
        )

    def test_passthrough_on_error_false_no_passthrough_warning(self, caplog):
        """When passthrough_on_error=False, no passthrough-specific warning."""
        mock_filter = MagicMock(spec=GuardFilter)
        mock_filter.filter_item.side_effect = ValueError("bad expression")
        evaluator = GuardEvaluator(guard_filter=mock_filter)

        guard_config = {
            "clause": "some_field == true",
            "behavior": "filter",
            "passthrough_on_error": False,
        }

        with caplog.at_level(
            logging.WARNING,
            logger=_EVALUATOR_LOGGER,
        ):
            result = evaluator.evaluate(
                item={"field": "value"},
                guard_config=guard_config,
            )

        assert result.should_execute is False

        passthrough_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "passthrough_on_error" in r.message
        ]
        assert len(passthrough_warnings) == 0, (
            "Should NOT log passthrough-specific warning when passthrough_on_error=False"
        )

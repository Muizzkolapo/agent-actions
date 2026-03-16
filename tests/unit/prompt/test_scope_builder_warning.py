"""Regression test: infer_dependencies fallback logs at WARNING level.

When ``infer_dependencies`` raises inside ``apply_observe_for_file_mode``,
the handler must emit a WARNING (not DEBUG) so operators can see that
dependency inference failed and the code fell back to raw dependencies.
"""

import logging
from unittest.mock import patch

import pytest

from agent_actions.prompt.context.scope_file_mode import apply_observe_for_file_mode

_LOGGER_NAME = "agent_actions.prompt.context.scope_file_mode"


@pytest.fixture()
def _enable_log_propagation():
    """Ensure the agent_actions logger propagates to root so caplog captures records.

    ``LoggerFactory.reset()`` (autouse conftest fixture) clears handlers but
    may leave ``propagate=False`` on the ``agent_actions`` logger, which
    prevents caplog from seeing any records.
    """
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = original


@pytest.mark.usefixtures("_enable_log_propagation")
class TestInferDependenciesFallbackWarning:
    """Verify the except-handler around infer_dependencies logs a warning."""

    def test_warning_logged_when_infer_dependencies_raises(self, caplog):
        """When infer_dependencies raises, a WARNING must be emitted."""
        agent_config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.question"]},
        }
        data = [{"question": "What?"}]
        agent_indices = {"upstream": 0, "current": 1}

        with patch(
            "agent_actions.prompt.context.scope_file_mode.infer_dependencies",
            side_effect=RuntimeError("boom"),
        ):
            with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
                result = apply_observe_for_file_mode(
                    data=data,
                    agent_config=agent_config,
                    agent_name="current",
                    agent_indices=agent_indices,
                )

        # The fallback should still produce a result (raw dependencies path)
        assert isinstance(result, list)

        # Verify the warning was emitted
        warning_messages = [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ]
        assert any(
            "infer_dependencies failed" in msg and "current" in msg
            for msg in warning_messages
        ), (
            f"Expected a WARNING containing 'infer_dependencies failed' and "
            f"'current', got: {warning_messages}"
        )

    def test_no_warning_when_infer_dependencies_succeeds(self, caplog):
        """When infer_dependencies succeeds, no fallback warning is emitted."""
        agent_config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.question"]},
        }
        data = [{"question": "What?"}]
        agent_indices = {"upstream": 0, "current": 1}

        with patch(
            "agent_actions.prompt.context.scope_file_mode.infer_dependencies",
            return_value=(["upstream"], []),
        ):
            with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
                apply_observe_for_file_mode(
                    data=data,
                    agent_config=agent_config,
                    agent_name="current",
                    agent_indices=agent_indices,
                )

        warning_messages = [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
            and "infer_dependencies failed" in record.message
        ]
        assert warning_messages == [], (
            f"No fallback warning expected on success, got: {warning_messages}"
        )

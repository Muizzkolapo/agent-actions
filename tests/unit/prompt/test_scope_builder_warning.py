"""Regression test: build_field_context_with_history logs at DEBUG when namespace missing.

With the additive content model, dependency data lives on the record's
namespaced content.  When a namespace is absent (skipped action), the
builder logs at DEBUG and continues — not an error.
"""

import logging

import pytest

from agent_actions.prompt.context.scope_builder import build_field_context_with_history

_LOGGER_NAME = "agent_actions.prompt.context.scope_builder"


@pytest.fixture()
def _enable_log_propagation():
    """Ensure the agent_actions logger propagates to root so caplog captures records."""
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = original


@pytest.mark.usefixtures("_enable_log_propagation")
class TestMissingNamespaceLogging:
    """Verify the builder logs gracefully when a namespace is missing."""

    def test_missing_namespace_logs_debug_not_error(self, caplog):
        """When a dependency namespace is absent on the record, DEBUG is logged."""
        current_item = {
            "content": {
                "extract": {"text": "hello"},
                # "classify" is NOT present (skipped)
            },
            "lineage": ["node-1"],
            "source_guid": "sg-1",
        }
        agent_config = {
            "dependencies": ["extract"],
            "context_scope": {
                "observe": ["extract.text", "classify.topic"],
            },
        }

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            result = build_field_context_with_history(
                agent_name="summarize",
                agent_config=agent_config,
                agent_indices={"extract": 0, "classify": 1, "summarize": 2},
                current_item=current_item,
                context_scope=agent_config["context_scope"],
            )

        # extract namespace loaded
        assert "extract" in result
        assert result["extract"]["text"] == "hello"

        # classify namespace absent — not in result, no error
        assert "classify" not in result

        # Should log at DEBUG, not WARNING or ERROR
        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("classify" in msg and "not found" in msg for msg in debug_messages)

    def test_all_namespaces_present(self, caplog):
        """When all namespaces are present, no missing-namespace log is emitted."""
        current_item = {
            "content": {
                "extract": {"text": "hello"},
                "classify": {"topic": "science"},
            },
            "lineage": ["node-1"],
            "source_guid": "sg-1",
        }
        agent_config = {
            "dependencies": ["extract"],
            "context_scope": {
                "observe": ["extract.text", "classify.topic"],
            },
        }

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            result = build_field_context_with_history(
                agent_name="summarize",
                agent_config=agent_config,
                agent_indices={"extract": 0, "classify": 1, "summarize": 2},
                current_item=current_item,
                context_scope=agent_config["context_scope"],
            )

        assert result["extract"]["text"] == "hello"
        assert result["classify"]["topic"] == "science"

        # No "not found" messages
        debug_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("not found" in msg for msg in debug_messages)

"""An action with no schema is not schema-checked, and says nothing about it.

Enforcement belongs to an `expect:` block, whose structural gate regenerates a
response the schema rejects; the runtime path here only reports a mismatch for an
action that has no such block. With no schema to compare against there is nothing
to report, and a warning emitted anyway would fire on every tool and HITL action.
"""

from unittest.mock import patch

from agent_actions.processing.helpers import _validate_llm_output_schema


class TestRuntimeWarning:
    @patch("agent_actions.processing.helpers.logger")
    def test_an_action_with_no_schema_is_not_warned_about(self, mock_logger):
        _validate_llm_output_schema({"any": "value"}, {}, "test_action")

        mock_logger.warning.assert_not_called()

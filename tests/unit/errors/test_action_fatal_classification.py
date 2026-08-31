"""``is_action_fatal`` must agree with what the strategies re-raise.

The online strategy's record loop re-raises exactly the action-fatal set and
tombstones the rest; the file collector consults ``is_action_fatal`` to decide
what escapes partial success. If the two drift, an error one layer escalates
is an error the other swallows.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import (
    AgentActionsError,
    ConfigurationError,
    EmptyOutputError,
    NetworkError,
    RecordContextError,
    SchemaValidationError,
    TemplateVariableError,
    exhaustion_halt,
    is_action_fatal,
)


def _template_error(missing: list) -> TemplateVariableError:
    return TemplateVariableError(
        missing_variables=missing,
        available_variables=["source"],
        agent_name="label_page",
        mode="online",
        cause=Exception("jinja"),
    )


class TestTheFatalSet:
    @pytest.mark.parametrize(
        "error",
        [
            exhaustion_halt("Retry exhausted (on_exhausted=raise)"),
            ConfigurationError("schema missing"),
            EmptyOutputError("no output with on_empty=error"),
            SchemaValidationError("output failed validation"),
            _template_error(missing=[]),
        ],
        ids=["halt", "configuration", "empty_output", "schema_validation", "broken_template"],
    )
    def test_what_the_strategies_reraise_is_fatal(self, error):
        assert is_action_fatal(error) is True

    def test_a_wrapped_halt_keeps_its_tag(self):
        wrapped = AgentActionsError("file failed", cause=exhaustion_halt("halted"))
        assert is_action_fatal(wrapped) is True


class TestTheRecoverableSet:
    @pytest.mark.parametrize(
        "error",
        [
            RecordContextError("record context incomplete"),
            _template_error(missing=["source.title"]),
            NetworkError("timeout"),
            AgentActionsError("wrapped file accident"),
            ValueError("unreadable row"),
        ],
        ids=["record_context", "missing_vars", "network", "wrapped_accident", "file_scoped"],
    )
    def test_per_item_accidents_are_not_fatal(self, error):
        assert is_action_fatal(error) is False

"""Tests for _compile_output_schema unsupported-type warning."""

import logging

import pytest

from agent_actions.output.response.expander import ActionExpander

LOGGER_NAME = "agent_actions.output.response.expander"


@pytest.fixture(autouse=True)
def _enable_propagation():
    """Ensure the entire agent_actions logger hierarchy propagates for caplog."""
    loggers = [
        logging.getLogger("agent_actions"),
        logging.getLogger(LOGGER_NAME),
    ]
    originals = [(lgr, lgr.propagate) for lgr in loggers]
    for lgr in loggers:
        lgr.propagate = True
    yield
    for lgr, orig in originals:
        lgr.propagate = orig


class TestCompileOutputSchemaWarning:
    """_compile_output_schema must warn when schema type is unsupported."""

    def test_warns_on_string_schema(self, caplog):
        """A string schema (not list or dict) should log a warning and be skipped."""
        agent = {"agent_type": "test_action", "schema": "unexpected_string_value"}

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            ActionExpander._compile_output_schema(agent, {})

        assert any("unsupported type" in msg.lower() for msg in caplog.messages)
        assert any("str" in msg for msg in caplog.messages)
        # json_output_schema should NOT be set
        assert "json_output_schema" not in agent

    def test_warns_on_int_schema(self, caplog):
        """An integer schema should log a warning and be skipped."""
        agent = {"agent_type": "test_action", "schema": 42}

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            ActionExpander._compile_output_schema(agent, {})

        assert any("unsupported type" in msg.lower() for msg in caplog.messages)
        assert any("int" in msg for msg in caplog.messages)
        assert "json_output_schema" not in agent

    def test_no_warning_for_dict_schema(self, caplog):
        """Dict schemas are supported — no warning should be emitted for the type check."""
        agent = {
            "agent_type": "test_action",
            "schema": {
                "fields": [{"id": "name", "type": "string", "required": True}],
                "name": "test",
            },
        }

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            ActionExpander._compile_output_schema(agent, {})

        assert not any("unsupported type" in msg.lower() for msg in caplog.messages)

    def test_no_warning_for_list_schema(self, caplog):
        """List schemas are supported — no warning should be emitted for the type check."""
        agent = {
            "agent_type": "test_action",
            "schema": [{"id": "name", "type": "string", "required": True}],
        }

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            ActionExpander._compile_output_schema(agent, {})

        assert not any("unsupported type" in msg.lower() for msg in caplog.messages)

    def test_skips_when_json_output_schema_already_set(self):
        """Should skip entirely if json_output_schema is already populated."""
        agent = {
            "agent_type": "test_action",
            "json_output_schema": {"type": "object"},
            "schema": "should_be_ignored",
        }

        ActionExpander._compile_output_schema(agent, {})

        # Original json_output_schema preserved
        assert agent["json_output_schema"] == {"type": "object"}

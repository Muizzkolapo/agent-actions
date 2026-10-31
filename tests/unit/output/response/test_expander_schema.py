"""Tests for _compile_output_schema unsupported-type warning."""

import logging

import pytest

from agent_actions.output.response.expander_schema import compile_output_schema

LOGGER_NAME = "agent_actions.output.response.expander"


class TestCompileOutputSchemaWarning:
    """_compile_output_schema must warn when schema type is unsupported."""

    @pytest.mark.parametrize(
        ("schema", "type_name"),
        [("unexpected_string_value", "str"), (42, "int")],
        ids=["str-schema", "int-schema"],
    )
    def test_warns_on_unsupported_schema_type(self, caplog, schema, type_name):
        agent = {"agent_type": "test_action", "schema": schema}

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            compile_output_schema(agent, {})

        assert any("unsupported type" in msg.lower() for msg in caplog.messages)
        assert any(type_name in msg for msg in caplog.messages)
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
            compile_output_schema(agent, {})

        assert not any("unsupported type" in msg.lower() for msg in caplog.messages)

    def test_no_warning_for_list_schema(self, caplog):
        """List schemas are supported — no warning should be emitted for the type check."""
        agent = {
            "agent_type": "test_action",
            "schema": [{"id": "name", "type": "string", "required": True}],
        }

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            compile_output_schema(agent, {})

        assert not any("unsupported type" in msg.lower() for msg in caplog.messages)

    def test_skips_when_json_output_schema_already_set(self):
        """Should skip entirely if json_output_schema is already populated."""
        agent = {
            "agent_type": "test_action",
            "json_output_schema": {"type": "object"},
            "schema": "should_be_ignored",
        }

        compile_output_schema(agent, {})

        # Original json_output_schema preserved
        assert agent["json_output_schema"] == {"type": "object"}

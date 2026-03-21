"""Tests for ResponseSchemaCompiler explicit-schema-dropped warning."""

import logging
from unittest.mock import patch

import pytest

from agent_actions.output.response.schema import ResponseSchemaCompiler

LOGGER_NAME = "agent_actions.output.response.schema"


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


class TestResponseSchemaCompilerWarning:
    """ResponseSchemaCompiler.compile() must warn when an explicit schema is silently dropped."""

    @patch(
        "agent_actions.output.response.schema._compile_schema_for_vendor",
        return_value=None,
    )
    @patch(
        "agent_actions.output.response.schema._load_inline_schema",
        return_value=({"name": "test", "fields": []}, "test"),
    )
    def test_warns_when_inline_schema_dropped(self, _load, _compile, caplog):
        """Warning emitted when inline schema compiles to None."""
        agent_config = {"schema": {"name": "test", "fields": []}}
        compiler = ResponseSchemaCompiler()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            compiled, _ = compiler.compile(agent_config, vendor="unknown_vendor")

        assert compiled is None
        assert any("explicitly configured" in msg for msg in caplog.messages)
        assert any("schema-constrained" in msg for msg in caplog.messages)

    @patch(
        "agent_actions.output.response.schema._compile_schema_for_vendor",
        return_value=None,
    )
    @patch(
        "agent_actions.output.response.schema._load_named_schema",
        return_value=({"name": "my_schema", "fields": []}, "my_schema"),
    )
    def test_warns_when_named_schema_dropped(self, _load, _compile, caplog):
        """Warning emitted when named schema compiles to None."""
        agent_config = {"schema_name": "my_schema"}
        compiler = ResponseSchemaCompiler()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            compiled, _ = compiler.compile(agent_config, vendor="unknown_vendor")

        assert compiled is None
        assert any("explicitly configured" in msg for msg in caplog.messages)

    @patch(
        "agent_actions.output.response.schema._compile_schema_for_vendor",
        return_value=None,
    )
    def test_no_warning_when_no_schema_configured(self, _compile, caplog):
        """No warning when there's no schema at all — nothing was 'explicitly configured'."""
        agent_config = {}
        compiler = ResponseSchemaCompiler()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            compiled, _ = compiler.compile(agent_config, vendor="openai")

        # No warning about explicitly configured schema
        assert not any("explicitly configured" in msg for msg in caplog.messages)

    def test_no_warning_when_compilation_succeeds(self, caplog):
        """No warning when schema compiles successfully."""
        agent_config = {
            "schema": {
                "name": "test_schema",
                "fields": [{"id": "result", "type": "string", "required": True}],
            }
        }
        compiler = ResponseSchemaCompiler()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            compiled, _ = compiler.compile(agent_config, vendor="openai")

        assert compiled is not None
        assert not any("explicitly configured" in msg for msg in caplog.messages)

    def test_no_warning_for_tool_vendor(self, caplog):
        """Tool vendor returns (None, {}) without any warning."""
        agent_config = {"schema": {"name": "test", "fields": []}}
        compiler = ResponseSchemaCompiler()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            compiled, _ = compiler.compile(agent_config, vendor="tool")

        assert compiled is None
        assert not any("explicitly configured" in msg for msg in caplog.messages)

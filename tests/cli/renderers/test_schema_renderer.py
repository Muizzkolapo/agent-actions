"""Tests for the SchemaRenderer."""

import pytest
from rich.console import Console

from agent_actions.cli.renderers.schema_renderer import SchemaRenderer
from agent_actions.models.action_schema import (
    ActionKind,
    ActionSchema,
    FieldInfo,
    FieldSource,
)


class TestSchemaRenderer:
    """Tests for SchemaRenderer class."""

    @pytest.fixture
    def console(self):
        """Create a console instance."""
        return Console(force_terminal=True, width=120)

    @pytest.fixture
    def renderer(self, console):
        """Create a renderer instance."""
        return SchemaRenderer(console)

    def test_format_input_summary_with_fields(self, renderer):
        """Test _format_input_summary shows required/optional fields."""
        schema = ActionSchema(
            name="tool_action",
            kind=ActionKind.TOOL,
            input_fields=[
                FieldInfo(name="text", source=FieldSource.TOOL_OUTPUT, is_required=True),
                FieldInfo(name="options", source=FieldSource.TOOL_OUTPUT, is_required=False),
            ],
        )

        result = renderer._format_input_summary(schema)

        assert "required" in result
        assert "text" in result
        assert "optional" in result
        assert "options" in result

    def test_format_output_summary_with_fields(self, renderer):
        """Test _format_output_summary shows available fields."""
        schema = ActionSchema(
            name="extractor",
            kind=ActionKind.LLM,
            output_fields=[
                FieldInfo(name="summary", source=FieldSource.SCHEMA),
                FieldInfo(name="facts", source=FieldSource.SCHEMA),
            ],
        )

        result = renderer._format_output_summary(schema)

        assert "facts" in result
        assert "summary" in result

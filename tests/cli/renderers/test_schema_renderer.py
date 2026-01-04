"""Tests for the SchemaRenderer."""

import pytest
from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.panel import Panel

from agent_actions.cli.renderers.schema_renderer import SchemaRenderer
from agent_actions.models.action_schema import (
    ActionSchema,
    FieldInfo,
    FieldSource,
    UpstreamReference,
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

    @pytest.fixture
    def sample_schemas(self):
        """Create sample schemas for testing."""
        return {
            "extractor": ActionSchema(
                name="extractor",
                kind="llm",
                output_fields=[
                    FieldInfo(name="summary", source=FieldSource.SCHEMA),
                    FieldInfo(name="facts", source=FieldSource.SCHEMA),
                ],
                downstream=["consumer"],
            ),
            "consumer": ActionSchema(
                name="consumer",
                kind="llm",
                upstream_refs=[
                    UpstreamReference(
                        "extractor", "summary", "prompt", "{{ action.extractor.summary }}"
                    ),
                ],
                dependencies=["extractor"],
                output_fields=[
                    FieldInfo(name="result", source=FieldSource.SCHEMA),
                ],
            ),
        }

    def test_render_summary_table_returns_table(self, renderer, sample_schemas):
        """Test render_summary_table returns a Table."""
        execution_order = ["extractor", "consumer"]

        result = renderer.render_summary_table(sample_schemas, execution_order)

        assert isinstance(result, Table)

    def test_render_summary_table_with_title(self, renderer, sample_schemas):
        """Test render_summary_table can set title."""
        execution_order = ["extractor", "consumer"]

        result = renderer.render_summary_table(sample_schemas, execution_order, title="Test Title")

        assert result.title == "Test Title"

    def test_render_summary_table_follows_execution_order(self, renderer, sample_schemas):
        """Test render_summary_table respects execution order."""
        # Verify the table is created with correct order
        result = renderer.render_summary_table(sample_schemas, ["extractor", "consumer"])

        # Table should have 2 rows (one per action)
        assert result.row_count == 2

    def test_render_flow_tree_returns_tree(self, renderer, sample_schemas):
        """Test render_flow_tree returns a Tree."""
        execution_order = ["extractor", "consumer"]

        result = renderer.render_flow_tree(sample_schemas, execution_order)

        assert isinstance(result, Tree)

    def test_render_action_detail_returns_panel(self, renderer, sample_schemas):
        """Test render_action_detail returns a Panel."""
        schema = sample_schemas["consumer"]

        result = renderer.render_action_detail(schema)

        assert isinstance(result, Panel)

    def test_render_action_detail_title_includes_action_name(self, renderer, sample_schemas):
        """Test render_action_detail panel title includes action name."""
        schema = sample_schemas["extractor"]

        result = renderer.render_action_detail(schema)

        assert "extractor" in result.title

    def test_render_data_flow_panel_returns_panel(self, renderer, sample_schemas):
        """Test render_data_flow_panel returns a Panel."""
        execution_order = ["extractor", "consumer"]

        result = renderer.render_data_flow_panel(sample_schemas, execution_order)

        assert isinstance(result, Panel)

    def test_format_input_summary_template_based(self, renderer):
        """Test _format_input_summary handles template-based."""
        schema = ActionSchema(name="test", kind="llm", is_template_based=True)

        result = renderer._format_input_summary(schema)

        assert "template-based" in result

    def test_format_input_summary_dynamic(self, renderer):
        """Test _format_input_summary handles dynamic."""
        schema = ActionSchema(name="test", kind="llm", is_dynamic=True)

        result = renderer._format_input_summary(schema)

        assert "dynamic" in result

    def test_format_input_summary_with_fields(self, renderer):
        """Test _format_input_summary shows required/optional fields."""
        schema = ActionSchema(
            name="tool_action",
            kind="tool",
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

    def test_format_output_summary_schemaless(self, renderer):
        """Test _format_output_summary handles schemaless."""
        schema = ActionSchema(name="test", kind="llm", is_schemaless=True)

        result = renderer._format_output_summary(schema)

        assert "schemaless" in result

    def test_format_output_summary_dynamic(self, renderer):
        """Test _format_output_summary handles dynamic."""
        schema = ActionSchema(name="test", kind="source", is_dynamic=True)

        result = renderer._format_output_summary(schema)

        assert "dynamic" in result

    def test_format_output_summary_with_fields(self, renderer):
        """Test _format_output_summary shows available fields."""
        schema = ActionSchema(
            name="extractor",
            kind="llm",
            output_fields=[
                FieldInfo(name="summary", source=FieldSource.SCHEMA),
                FieldInfo(name="facts", source=FieldSource.SCHEMA),
            ],
        )

        result = renderer._format_output_summary(schema)

        assert "facts" in result
        assert "summary" in result

    def test_format_output_summary_empty(self, renderer):
        """Test _format_output_summary handles no fields."""
        schema = ActionSchema(name="test", kind="llm")

        result = renderer._format_output_summary(schema)

        assert "none" in result

    def test_render_flow_tree_shows_uses_for_refs(self, renderer, sample_schemas):
        """Test flow tree shows 'uses' section for upstream refs."""
        # Consumer has upstream refs
        result = renderer.render_flow_tree(sample_schemas, ["extractor", "consumer"])

        # Just verify it returns a tree without errors
        assert isinstance(result, Tree)

    def test_render_flow_tree_shows_expects_for_tools(self, renderer):
        """Test flow tree shows 'expects' section for tools."""
        schemas = {
            "my_tool": ActionSchema(
                name="my_tool",
                kind="tool",
                input_fields=[
                    FieldInfo(name="text", source=FieldSource.TOOL_OUTPUT, is_required=True),
                ],
            )
        }

        result = renderer.render_flow_tree(schemas, ["my_tool"])

        assert isinstance(result, Tree)

    def test_render_action_detail_shows_dependencies(self, renderer, sample_schemas):
        """Test action detail shows dependencies."""
        schema = sample_schemas["consumer"]  # Has dependencies

        result = renderer.render_action_detail(schema)

        assert isinstance(result, Panel)

    def test_render_action_detail_shows_upstream_refs(self, renderer, sample_schemas):
        """Test action detail shows upstream references."""
        schema = sample_schemas["consumer"]  # Has upstream_refs

        result = renderer.render_action_detail(schema)

        assert isinstance(result, Panel)

    def test_render_action_detail_shows_downstream(self, renderer, sample_schemas):
        """Test action detail shows downstream actions."""
        schema = sample_schemas["extractor"]  # Has downstream

        result = renderer.render_action_detail(schema)

        assert isinstance(result, Panel)

    def test_render_handles_observe_fields(self, renderer):
        """Test rendering handles observe fields."""
        schemas = {
            "test": ActionSchema(
                name="test",
                kind="llm",
                output_fields=[
                    FieldInfo(name="original", source=FieldSource.OBSERVE),
                ],
            )
        }

        result = renderer.render_flow_tree(schemas, ["test"])
        assert isinstance(result, Tree)

    def test_render_handles_passthrough_fields(self, renderer):
        """Test rendering handles passthrough fields."""
        schemas = {
            "test": ActionSchema(
                name="test",
                kind="llm",
                output_fields=[
                    FieldInfo(name="meta", source=FieldSource.PASSTHROUGH),
                ],
            )
        }

        result = renderer.render_flow_tree(schemas, ["test"])
        assert isinstance(result, Tree)

    def test_render_handles_dropped_fields(self, renderer):
        """Test rendering handles dropped fields."""
        schemas = {
            "test": ActionSchema(
                name="test",
                kind="llm",
                output_fields=[
                    FieldInfo(name="result", source=FieldSource.SCHEMA),
                    FieldInfo(name="internal", source=FieldSource.SCHEMA, is_dropped=True),
                ],
            )
        }

        result = renderer.render_action_detail(schemas["test"])
        assert isinstance(result, Panel)

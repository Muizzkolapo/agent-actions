"""`agac schema` prints a summary table and a data-flow tree of each action's inputs
and outputs, in execution order.
"""

import io

import pytest
from rich.console import Console

from agent_actions.cli.renderers.schema_renderer import SchemaRenderer
from agent_actions.models.action_schema import ActionKind, ActionSchema, FieldInfo, FieldSource


def _render(renderable) -> str:
    console = Console(file=io.StringIO(), width=160, record=True, color_system=None)
    console.print(renderable)
    return console.export_text()


@pytest.fixture
def renderer() -> SchemaRenderer:
    return SchemaRenderer(Console(width=160))


SCHEMAS = {
    "source": ActionSchema(
        name="source",
        kind=ActionKind.SOURCE,
        output_fields=[FieldInfo(name="text", source=FieldSource.SCHEMA)],
    ),
    "extract": ActionSchema(
        name="extract",
        kind=ActionKind.LLM,
        output_fields=[
            FieldInfo(name="facts", source=FieldSource.SCHEMA),
            FieldInfo(name="text", source=FieldSource.OBSERVE),
            FieldInfo(name="page_id", source=FieldSource.PASSTHROUGH),
            FieldInfo(name="raw", source=FieldSource.TOOL_OUTPUT),
            FieldInfo(name="secret", source=FieldSource.SCHEMA, is_dropped=True),
        ],
    ),
    "score": ActionSchema(
        name="score",
        kind=ActionKind.TOOL,
        input_fields=[
            FieldInfo(name="facts", source=FieldSource.INPUT, is_required=True),
            FieldInfo(name="weights", source=FieldSource.INPUT, is_required=False),
        ],
    ),
    "route": ActionSchema(name="route", kind=ActionKind.TOOL, is_dynamic=True),
    "write": ActionSchema(
        name="write", kind=ActionKind.LLM, is_schemaless=True, is_template_based=True
    ),
}
ORDER = ["source", "extract", "score", "route", "write"]


class TestSummaryTable:
    def test_each_action_is_a_row_in_execution_order_with_its_kind(self, renderer):
        text = _render(renderer.render_summary_table(SCHEMAS, ORDER, title="Schemas"))

        positions = [text.index(f"│ {name}") for name in ORDER]
        assert positions == sorted(positions)
        assert "Schemas" in text
        for name in ORDER:
            row = next(line for line in text.splitlines() if line.startswith(f"│ {name} "))
            assert SCHEMAS[name].kind.value in row

    def test_an_action_without_a_schema_is_left_out(self, renderer):
        text = _render(renderer.render_summary_table(SCHEMAS, ["missing", "source"]))

        assert "missing" not in text
        assert "source" in text

    def test_outputs_show_the_fields_that_are_not_dropped(self, renderer):
        text = _render(renderer.render_summary_table(SCHEMAS, ["extract"]))

        assert "facts, page_id, raw, text" in text
        assert "secret" not in text

    def test_inputs_split_into_required_and_optional(self, renderer):
        text = _render(renderer.render_summary_table(SCHEMAS, ["score"]))

        assert "required: facts" in text
        assert "optional: weights" in text

    def test_a_dynamic_action_has_dynamic_inputs_and_outputs(self, renderer):
        text = _render(renderer.render_summary_table(SCHEMAS, ["route"]))

        assert text.count("(dynamic)") == 2

    def test_a_template_and_schemaless_action_is_marked_as_such(self, renderer):
        text = _render(renderer.render_summary_table(SCHEMAS, ["write"]))

        assert "(template-based)" in text
        assert "(schemaless)" in text

    def test_an_action_with_no_fields_shows_none(self, renderer):
        empty = {"bare": ActionSchema(name="bare", kind=ActionKind.LLM)}

        text = _render(renderer.render_summary_table(empty, ["bare"]))

        assert text.count("(none)") == 2


class TestFlowTree:
    def test_the_tree_lists_actions_in_order_with_their_kind(self, renderer):
        text = _render(renderer.render_flow_tree(SCHEMAS, ORDER))

        lines = [f"{name} ({SCHEMAS[name].kind.value})" for name in ORDER]
        positions = [text.index(line) for line in lines]
        assert positions == sorted(positions)
        assert text.startswith("Flow Visualization")

    def test_a_source_action_is_marked_as_the_workflow_input(self, renderer):
        text = _render(renderer.render_flow_tree(SCHEMAS, ["source"]))

        assert "(workflow input)" in text
        assert "produces:" in text

    def test_a_tool_lists_what_it_expects_marking_optional_inputs(self, renderer):
        text = _render(renderer.render_flow_tree(SCHEMAS, ["score"]))

        assert "expects:" in text
        assert "weights (optional)" in text
        assert "facts (optional)" not in text

    def test_a_dynamic_action_says_its_output_is_dynamic(self, renderer):
        text = _render(renderer.render_flow_tree(SCHEMAS, ["route"]))

        assert "(dynamic output)" in text

    def test_outputs_say_where_each_field_comes_from(self, renderer):
        text = _render(renderer.render_flow_tree(SCHEMAS, ["extract"]))

        assert "text (observe)" in text
        assert "page_id (passthrough)" in text
        assert "facts" in text and "raw" in text
        assert "secret" not in text

    def test_dropped_fields_show_only_in_the_verbose_view(self, renderer):
        brief = _render(renderer.render_flow_tree(SCHEMAS, ["extract"], verbose=False))
        verbose = _render(renderer.render_flow_tree(SCHEMAS, ["extract"], verbose=True))

        assert "dropped:" not in brief
        assert "dropped:" in verbose
        assert "secret" in verbose

    def test_a_schemaless_action_says_so_in_the_tree(self, renderer):
        text = _render(renderer.render_flow_tree(SCHEMAS, ["write", "missing"]))

        assert "(schemaless)" in text
        assert "missing" not in text

    def test_the_data_flow_panel_wraps_the_verbose_tree(self, renderer):
        text = _render(renderer.render_data_flow_panel(SCHEMAS, ["extract"]))

        assert "Workflow Data Flow" in text
        assert "dropped:" in text

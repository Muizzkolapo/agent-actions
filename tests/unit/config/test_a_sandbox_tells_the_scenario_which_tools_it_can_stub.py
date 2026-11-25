"""In sandbox mode the scenario is told each tool action, and why it takes no ``stub``.

The mock builds a stubbed tool's output from its output schema, one record for one input.
A tool with no schema, a FILE tool and a built-in tool cannot be stubbed.
"""

from __future__ import annotations

from agent_actions.config import sandbox

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}


def _configs() -> dict[str, dict]:
    return {
        "extract": {"kind": "llm", "model_vendor": "openai"},
        "search": {"kind": "tool", "granularity": "Record", "json_output_schema": SCHEMA},
        "plain": {"kind": "tool", "granularity": "Record", "json_output_schema": None},
        "merge": {"kind": "tool", "granularity": "File", "json_output_schema": SCHEMA},
        "pick_branch": {
            "kind": "tool",
            "granularity": "Record",
            "json_output_schema": SCHEMA,
            "_builtin": {"tool": "route", "field": "extract.kind", "cases": ["a"]},
        },
        "fetch_1": {
            "kind": "tool",
            "json_output_schema": SCHEMA,
            "is_versioned_agent": True,
            "version_base_name": "fetch",
        },
        "review": {"kind": "hitl"},
    }


def test_each_tool_action_is_returned_and_no_other_kind():
    assert list(sandbox.tool_actions(_configs())) == [
        "search",
        "plain",
        "merge",
        "pick_branch",
        "fetch_1",
    ]


def test_a_record_tool_with_an_output_schema_can_be_stubbed():
    tools = sandbox.tool_actions(_configs())

    assert tools["search"].cannot_stub is None
    assert (tools["fetch_1"].group, tools["fetch_1"].cannot_stub) == ("fetch", None)
    assert tools["search"].group is None


def test_a_tool_the_mock_cannot_build_says_why():
    tools = sandbox.tool_actions(_configs())

    assert "has no output schema" in tools["plain"].cannot_stub
    assert "granularity File" in tools["merge"].cannot_stub
    assert "built-in tool" in tools["pick_branch"].cannot_stub


def test_the_loaded_scenario_says_which_tools_it_stubs(tmp_path):
    (tmp_path / "sandbox.yml").write_text("actions:\n  search: {stub: true}\n")

    assert not sandbox.stubs("search")
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(tmp_path, {"extract": None}, sandbox.tool_actions(_configs()))

        assert sandbox.stubs("search") and not sandbox.stubs("plain")
        assert sandbox.stubbed_tools() == ["search"]
    assert not sandbox.stubs("search")
    assert sandbox.stubbed_tools() == []

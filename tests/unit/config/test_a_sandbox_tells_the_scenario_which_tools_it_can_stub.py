"""In sandbox mode the scenario is told each tool action, and why it takes no ``stub``.

The mock builds a stubbed tool's output from its output schema, one record for one input.
A tool with no schema, a FILE tool and a built-in tool cannot be stubbed. ``json_mode:
false`` is a setting of a model call, so a stubbed tool still takes a ``pin`` under it.
"""

from __future__ import annotations

import pytest

from agent_actions.config import sandbox
from agent_actions.config.schema import ActionKind
from agent_actions.errors import ConfigurationError
from agent_actions.models.action_schema import ActionSchema, FieldInfo, FieldSource

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


def _schema(name: str, kind: ActionKind) -> ActionSchema:
    return ActionSchema(
        name=name, kind=kind, output_fields=[FieldInfo("title", FieldSource.SCHEMA)]
    )


def _check_outputs_in_text_mode(tmp_path, scenario: str) -> None:
    """Check a scenario against a workflow whose defaults set ``json_mode: false``."""
    (tmp_path / "sandbox.yml").write_text(scenario)
    configs = _configs()
    configs["extract"] = {**configs["extract"], "model_vendor": sandbox.SANDBOX_VENDOR}
    for config in configs.values():
        config["json_mode"] = False
    schemas = {
        "extract": _schema("extract", ActionKind.LLM),
        "search": _schema("search", ActionKind.TOOL),
    }
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(tmp_path, {"extract": None}, sandbox.tool_actions(configs))
        sandbox.check_scenario_outputs(schemas, configs)


def test_a_stubbed_tool_takes_a_pin_when_json_mode_is_false(tmp_path):
    _check_outputs_in_text_mode(tmp_path, "actions:\n  search: {stub: true, pin: {title: Dune}}\n")


def test_a_stubbed_tool_pin_is_checked_against_its_schema_when_json_mode_is_false(tmp_path):
    with pytest.raises(ConfigurationError, match=r"actions\.search\.pin\.isbn: the output"):
        _check_outputs_in_text_mode(tmp_path, "actions:\n  search: {stub: true, pin: {isbn: x}}\n")


def test_an_llm_action_in_text_mode_takes_no_pin(tmp_path):
    with pytest.raises(ConfigurationError, match=r"\(text mode\), so it takes no pin"):
        _check_outputs_in_text_mode(tmp_path, "actions:\n  extract: {pin: {title: Dune}}\n")

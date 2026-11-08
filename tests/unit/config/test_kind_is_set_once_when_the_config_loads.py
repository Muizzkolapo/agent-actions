"""An action's kind is decided once, when the config loads, from ``kind`` or ``model_vendor``.

Each site used to decide again by its own rule: the pipeline lowercased the vendor,
the invocation factory compared it exactly, so ``agac inspect`` and ``agac run`` could
treat one action two ways. Every site now reads the ``kind`` the expander wrote.
"""

import re
from pathlib import Path

import pytest

from agent_actions.output.response.expander import ActionExpander
from agent_actions.processing.helpers import _is_tool_action, bypasses_expectations

SCHEMA = {"answer": "string"}


def _expand(action: dict, defaults: dict | None = None) -> dict:
    expanded = ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "actions": [{"name": "a1", "intent": "i", **action}],
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}
            | (defaults or {}),
        }
    )
    return expanded["wf"][0]


def test_a_vendor_only_tool_is_expanded_with_kind_tool():
    agent = _expand({"model_vendor": "tool", "impl": "m.f", "schema": SCHEMA})

    assert agent["kind"] == "tool"
    assert agent["model_vendor"] == "tool"
    assert agent["model_name"] == "m.f"


@pytest.mark.parametrize("vendor", ["Tool", "TOOL"])
def test_a_vendor_spelled_in_capitals_is_the_same_tool(vendor):
    agent = _expand({"model_vendor": vendor, "impl": "m.f", "schema": SCHEMA})

    assert (agent["kind"], agent["model_vendor"]) == ("tool", "tool")


def test_a_vendor_only_hitl_is_expanded_with_kind_hitl():
    agent = _expand({"model_vendor": "hitl", "hitl": {"port": 3001, "instructions": "Review"}})

    assert (agent["kind"], agent["model_vendor"]) == ("hitl", "hitl")


def test_a_kind_from_defaults_is_written_with_its_vendor():
    agent = _expand({"impl": "m.f", "schema": SCHEMA}, defaults={"kind": "tool"})

    assert (agent["kind"], agent["model_vendor"]) == ("tool", "tool")


def test_an_llm_action_is_expanded_with_kind_llm():
    agent = _expand({"prompt": "p"})

    assert (agent["kind"], agent["model_vendor"]) == ("llm", "openai")


def test_runtime_sites_read_the_expanded_kind():
    agent = _expand(
        {"model_vendor": "tool", "impl": "m.f", "schema": SCHEMA, "granularity": "file"}
    )

    assert _is_tool_action(agent)
    assert bypasses_expectations(agent)


def test_no_site_outside_the_loader_checks_kind_or_vendor():
    """The vendor-only spelling stops being a special case anywhere but routing_kind."""
    source = Path(__file__).resolve().parents[3] / "agent_actions"
    either = re.compile(
        r"""(kind|vendor)[^\n]{0,60}["'](tool|hitl)["'][^\n]{0,60}\bor\b[^\n]{0,60}(kind|vendor)"""
    )
    offenders = [
        f"{path.relative_to(source)}:{number}"
        for path in source.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if either.search(line)
    ]

    assert offenders == []

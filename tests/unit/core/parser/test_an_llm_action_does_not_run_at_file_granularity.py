"""An LLM action runs per record; FILE granularity belongs to tools and HITL.

Written on the action, `granularity: file` is the author's mistake and is refused at
expansion, which `agac inspect` and `agac run` both go through. Inherited from
`defaults:`, it was written for the workflow's tools, so an LLM action stays at Record.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.output.response.expander import ActionExpander

MODEL = {"model_vendor": "openai", "model_name": "gpt-4o", "api_key": "k"}
TOOL = {
    "kind": "tool",
    "impl": "mod.fn",
    "schema": {"name": "t", "fields": [{"name": "out", "type": "string"}]},
}
HITL = {"kind": "hitl", "hitl": {"port": 3999, "instructions": "Review"}}
REFUSAL = (
    "FILE granularity is only supported for tool and hitl actions. "
    "LLM actions must use RECORD granularity. "
    "Remove 'granularity: file' from the action, or make it a tool."
)


def _granularity(action: dict, defaults: dict | None = None) -> str:
    agents = ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "defaults": {**MODEL, **(defaults or {})},
            "actions": [{"prompt": "p", **action}],
        }
    )
    return next(a for group in agents.values() for a in group)["granularity"]


@pytest.mark.parametrize("written", ["file", "File", "FILE"])
def test_an_llm_action_that_sets_file_granularity_is_refused(written):
    with pytest.raises(ConfigurationError) as refused:
        _granularity({"name": "label_page", "granularity": written})

    assert str(refused.value) == REFUSAL
    assert refused.value.context == {"agent_name": "label_page"}


def test_an_explicit_llm_kind_is_refused_the_same_way():
    with pytest.raises(ConfigurationError) as refused:
        _granularity({"name": "label_page", "kind": "llm", "granularity": "file"})

    assert str(refused.value) == REFUSAL


def test_a_tool_that_sets_file_granularity_runs_at_file():
    assert _granularity({"name": "t", "granularity": "file", **TOOL}) == "File"


def test_an_llm_action_does_not_inherit_file_granularity_from_defaults():
    assert _granularity({"name": "label_page"}, {"granularity": "File"}) == "Record"


def test_a_tool_inherits_file_granularity_from_the_same_defaults():
    assert _granularity({"name": "t", **TOOL}, {"granularity": "File"}) == "File"


def test_a_hitl_action_stays_at_file_under_record_defaults():
    assert _granularity({"name": "review", **HITL}, {"granularity": "Record"}) == "File"


def test_an_llm_action_that_sets_record_under_file_defaults_keeps_it():
    assert _granularity({"name": "a", "granularity": "record"}, {"granularity": "File"}) == "Record"

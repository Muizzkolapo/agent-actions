"""A tool or hitl action under run_mode: batch loads and passes preflight with no batch message.

Built the way a run builds it: the workflow schema, then the expander, then
preflight over the expanded agents.
"""

import pytest

from agent_actions.config.schema import WorkflowConfig
from agent_actions.output.response.expander import ActionExpander
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

DEFAULTS = {
    "model_vendor": "openai",
    "model_name": "gpt-4o-mini",
    "api_key": "KEY",
    "run_mode": "batch",
}


@pytest.fixture(autouse=True)
def _skip_key_presence_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


def _agents(actions: list[dict]) -> dict[str, dict]:
    workflow = WorkflowConfig.model_validate(
        {"name": "w", "description": "d", "defaults": DEFAULTS, "actions": actions}
    )
    expanded = {
        "name": "w",
        "actions": [
            a.model_dump(mode="python", exclude_unset=True, by_alias=True) for a in workflow.actions
        ],
        "defaults": workflow.defaults.model_dump(mode="python", exclude_unset=True, by_alias=True),
    }
    return {a["agent_type"]: a for a in ActionExpander.expand_actions_to_agents(expanded)["w"]}


def _tool(name: str, **extra) -> dict:
    return {
        "name": name,
        "intent": "i",
        "kind": "tool",
        "impl": "split_rows",
        "schema": {"topic": "string"},
        **extra,
    }


def _hitl(name: str, **extra) -> dict:
    return {
        "name": name,
        "intent": "i",
        "kind": "hitl",
        "hitl": {"instructions": "Approve."},
        **extra,
    }


def _batch_messages(items) -> list[str]:
    return sorted(i.message for i in items if "batch" in i.message.lower())


def test_a_tool_action_that_sets_batch_itself_loads():
    agents = _agents([_tool("split", run_mode="batch")])

    assert agents["split"]["model_vendor"] == "tool"


def test_preflight_says_nothing_about_batch_for_tool_or_hitl_actions():
    agents = _agents(
        [
            _tool("split", run_mode="batch"),
            _tool("inherited_split"),
            _hitl("review", run_mode="batch"),
            _hitl("inherited_review"),
            {"name": "define", "intent": "i", "kind": "llm", "prompt": "Define it."},
        ]
    )

    result = WorkflowResolutionService(action_configs=agents).resolve_all()

    assert _batch_messages(result.errors) == []
    assert _batch_messages(result.warnings) == []


def test_an_llm_action_that_cannot_batch_is_still_refused_after_loading():
    agents = _agents(
        [
            {
                "name": "classify",
                "intent": "i",
                "kind": "llm",
                "prompt": "Classify it.",
                "model_vendor": "cohere",
            }
        ]
    )

    result = WorkflowResolutionService(action_configs=agents).resolve_all()

    assert _batch_messages(result.errors) == [
        "Action 'classify': vendor 'cohere' does not support run_mode: batch."
    ]

"""`observe` and `drop` are directives under `context_scope:`, not keys beside it.

Driven through the path `ConfigManager` uses — validate, dump, expand — because a
key that validates and is then never read looks correct at every layer above the
agent dict.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import WorkflowConfig
from agent_actions.output.response.expander import ActionExpander

DIRECTIVES = ["observe", "drops", "drop", "passthrough"]

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}


def _workflow(defaults=None, action=None):
    return {
        "name": "wf",
        "description": "d",
        "version": "1.0",
        "defaults": {**BASE_DEFAULTS, **(defaults or {})},
        "actions": [{"name": "a1", "intent": "i", "prompt": "p", **(action or {})}],
    }


def _load_and_expand(config):
    """Validate then expand, the way ConfigManager.get_user_agents does."""
    workflow = WorkflowConfig.model_validate(config)
    expanded = ActionExpander.expand_actions_to_agents(
        {
            "name": workflow.name,
            "actions": [
                a.model_dump(mode="python", exclude_unset=True, by_alias=True)
                for a in workflow.actions
            ],
            "defaults": workflow.defaults.model_dump(
                mode="python", exclude_unset=True, by_alias=True
            )
            if workflow.defaults
            else {},
        }
    )
    return expanded[workflow.name][0]


@pytest.mark.parametrize("directive", DIRECTIVES)
@pytest.mark.parametrize("level", ["defaults", "action"])
def test_a_directive_written_beside_context_scope_is_refused_not_ignored(directive, level):
    """Either the value reaches the agent or the load refuses it. Accepting a key
    and then reading it from nowhere is the one outcome a config author cannot see."""
    written = {directive: ["src.f"]}
    config = _workflow(defaults=written) if level == "defaults" else _workflow(action=written)

    try:
        agent = _load_and_expand(config)
    except ValidationError:
        return

    scope = agent.get("context_scope") or {}
    assert ["src.f"] in (scope.get(directive), agent.get(directive)), (
        f"{level}-level {directive!r} loaded without error and reached nothing: "
        f"agent[{directive!r}]={agent.get(directive)!r}, context_scope={scope!r}"
    )


@pytest.mark.parametrize("directive", DIRECTIVES)
def test_the_defaults_refusal_names_the_block_that_takes_the_directive(directive):
    with pytest.raises(ValidationError) as exc:
        WorkflowConfig.model_validate(_workflow(defaults={directive: ["src.f"]}))

    message = str(exc.value)
    assert f"unknown defaults key '{directive}'" in message
    assert "context_scope" in message


@pytest.mark.parametrize("directive", DIRECTIVES)
def test_the_action_refusal_says_where_the_directive_belongs(directive):
    """A directive beside `context_scope:` instead of under it is the shape a YAML
    indentation slip produces, so the refusal has to name the indentation."""
    with pytest.raises(ValidationError) as exc:
        WorkflowConfig.model_validate(_workflow(action={directive: ["src.f"]}))

    message = str(exc.value)
    assert directive in message
    assert "context_scope" in message


@pytest.mark.parametrize("level", ["defaults", "action"])
def test_the_spelling_that_is_read_still_reaches_the_agent(level):
    written = {"context_scope": {"observe": ["src.f"]}}
    config = _workflow(defaults=written) if level == "defaults" else _workflow(action=written)

    agent = _load_and_expand(config)

    assert agent["context_scope"]["observe"] == ["src.f"]


def test_an_action_directive_merges_over_the_workflow_one():
    agent = _load_and_expand(
        _workflow(
            defaults={"context_scope": {"observe": ["src.a"]}},
            action={"context_scope": {"observe": ["src.b"]}},
        )
    )

    assert agent["context_scope"]["observe"] == ["src.a", "src.b"]

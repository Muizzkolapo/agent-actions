"""`observe` and `drop` are directives under `context_scope:`, not keys beside it.

Driven through the path `ConfigManager` uses — validate, dump, expand — because a
key that validates and is then never read looks correct at every layer above the
agent dict.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import WorkflowConfig
from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import normalize_context_scope
from agent_actions.output.response.expander import ActionExpander

DIRECTIVES = ["observe", "drops", "drop", "passthrough"]

# What each spelling should be written as once it is under `context_scope:`.
CANONICAL = {"observe": "observe", "drops": "drop", "drop": "drop", "passthrough": "passthrough"}

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
@pytest.mark.parametrize("level,surface", [("defaults", "defaults"), ("action", "action")])
def test_the_refusal_says_where_the_directive_belongs(directive, level, surface):
    """A directive beside `context_scope:` instead of under it is the shape a YAML
    indentation slip produces, so the refusal has to name the indentation. Both
    blocks say it: a defaults-level one is the spelling found in the wild."""
    written = {directive: ["src.f"]}
    config = _workflow(defaults=written) if level == "defaults" else _workflow(action=written)

    with pytest.raises(ValidationError) as exc:
        WorkflowConfig.model_validate(config)

    message = str(exc.value)
    assert f"'{directive}' is a context_scope directive, not a {surface} key" in message
    assert "indent under context_scope:" in message


@pytest.mark.parametrize("directive", DIRECTIVES)
@pytest.mark.parametrize("level", ["defaults", "action"])
def test_the_refusal_shows_a_nesting_that_is_itself_read(directive, level):
    """The remedy names the spelling the framework reads. Printing the offending
    key back verbatim would send `drops:` under context_scope, where it is as
    inert as it was beside it."""
    written = {directive: ["src.f"]}
    config = _workflow(defaults=written) if level == "defaults" else _workflow(action=written)

    with pytest.raises(ValidationError) as exc:
        WorkflowConfig.model_validate(config)

    assert f"    {CANONICAL[directive]}:" in str(exc.value)


def test_a_directive_spelling_the_framework_does_not_read_is_refused_under_context_scope():
    """`drops` is not a directive. Accepted there it would drop nothing, which is
    the same silence one level down."""
    with pytest.raises(ConfigurationError) as exc:
        normalize_context_scope({"drops": ["src.f"]}, version_base_map={})

    message = str(exc.value)
    assert "context_scope.drops is not a valid directive" in message
    assert "drop, observe, passthrough, seed" in message


@pytest.mark.parametrize("directive", ["observe", "drops"])
def test_the_legacy_agents_block_refuses_the_directive_too(directive):
    """`agents:` configs validate against a model that allows extras, so a key
    removed from the action schema passes through there untouched."""
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = {}
    manager.tool_path = None
    manager.agent_configs = {}

    with pytest.raises(ConfigurationError, match="removed field spelling") as exc:
        manager.merge_agent_configs(
            [
                {
                    "agent_type": "a1",
                    "model_vendor": "openai",
                    "model_name": "gpt-4",
                    "chunk_config": {},
                    directive: ["src.f"],
                }
            ]
        )

    assert exc.value.context["replacements"][directive].startswith("context_scope.")


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

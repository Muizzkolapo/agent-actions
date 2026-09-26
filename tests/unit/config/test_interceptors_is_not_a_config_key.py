"""`interceptors:` is not a config key — the system it configured was deleted.

The interceptor runtime went in `f97267b1` ("remove reprompt and interceptor
systems"), which took the factory, the validation interceptor and the realtime
interceptor service. Its config surface did not go with it: the key stayed
declared on `ActionConfig` and the expander kept copying it onto the agent. #965
retired the `reprompt:` half of that same deletion; this is the other half.

Pinned on both sites separately, because either one alone still loses the value
in silence: a declaration with no copy accepts a key that reaches nothing, and a
copy with no declaration puts a key on the agent that no schema admits. The
copy is the worse of the two — the value *is* visible on the agent config, so
anything dumping or inspecting that config shows it present and applied.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig, WorkflowConfig
from agent_actions.output.response.expander import ActionExpander

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}

# The shape the deleted runtime took, so the probe is refused for being the key
# it is rather than for being malformed.
BLOCK = [{"type": "validation", "name": "schema_check"}]


def _workflow(action=None):
    return {
        "name": "wf",
        "description": "d",
        "version": "1.0",
        "defaults": dict(BASE_DEFAULTS),
        "actions": [{"name": "a1", "intent": "i", "prompt": "p", **(action or {})}],
    }


def _expand(action):
    """Expand a raw action dict, skipping validation.

    Deliberately not through `WorkflowConfig`: once the declaration is gone the
    schema refuses this input, and a test that could only reach the expander
    through the schema would stop exercising it at exactly the point the
    expander's own half of the fix is what needs proving.
    """
    expanded = ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "actions": [{"name": "a1", "intent": "i", "prompt": "p", **action}],
            "defaults": dict(BASE_DEFAULTS),
        }
    )
    return expanded["wf"][0]


def test_an_action_carrying_interceptors_is_refused_at_load():
    """A workflow naming a retired key fails, rather than loading and doing nothing."""
    with pytest.raises(ValidationError) as caught:
        WorkflowConfig.model_validate(_workflow({"interceptors": BLOCK}))

    assert "interceptors" in str(caught.value)


@pytest.mark.parametrize("model", [ActionConfig, DefaultsConfig])
def test_no_config_model_declares_interceptors(model):
    """`defaults:` already refused it by not declaring it; the action surface is
    the one that accepted it, and the two must agree."""
    assert "interceptors" not in model.model_fields


def test_the_expander_hands_no_interceptors_to_the_agent():
    """The copy is what made the dead key look live, so its absence is asserted
    on the agent the expander actually built."""
    agent = _expand({"interceptors": BLOCK})

    assert "interceptors" not in agent, (
        f"the expander copied a key no stage reads onto the agent: {agent.get('interceptors')!r}"
    )


def test_the_expander_still_carries_the_key_it_processes_beside_interceptors():
    """Guard on the guard: the two assertions above both pass if the expander
    stopped producing agents at all, or ignored the block it was handed. The
    `version_consumption` copy sits in the same step and must survive."""
    agent = _expand({"version_consumption": {"source": "gen", "pattern": "merge"}})

    assert agent["version_consumption_config"] == {"source": "gen", "pattern": "merge"}

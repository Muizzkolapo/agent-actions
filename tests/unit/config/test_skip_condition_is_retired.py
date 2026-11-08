"""`skip_condition` (and its old spelling `skip_if`) is refused with the guard to use (1701).

No `actions:` workflow could set it, and on the older `agents:` surface its model and
its only reader disagreed on its shape. A guard with `on_false: skip` skips records.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import ActionConfig
from agent_actions.errors import ConfigurationError


@pytest.mark.parametrize("key", ["skip_condition", "skip_if"])
def test_an_action_naming_it_is_told_to_use_a_guard(key):
    with pytest.raises(ValidationError) as refused:
        ActionConfig.model_validate(
            {"name": "a", "intent": "x", "kind": "tool", "impl": "f", key: "x > 1"}
        )

    text = str(refused.value)
    assert f"'{key}' is no longer read and configures nothing" in text
    assert "guard: condition plus on_false: skip" in text


@pytest.mark.parametrize("key", ["skip_condition", "skip_if"])
@pytest.mark.parametrize("surface", ["agent", "default_agent_config"])
def test_the_agents_surface_refuses_it_too(key, surface):
    cm = ConfigManager.__new__(ConfigManager)
    cm.default_config = {}
    cm.tool_path = None
    cm.agent_configs = {}
    agent = {"agent_type": "consumer", "chunk_config": {}}
    if surface == "agent":
        agent[key] = "x > 1"
    else:
        cm.default_config = {"default_agent_config": {key: "x > 1"}}

    with pytest.raises(ConfigurationError) as refused:
        cm.merge_agent_configs([agent])

    assert f"'{key}' is no longer read" in str(refused.value)
    assert "on_false: skip" in str(refused.value)

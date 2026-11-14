"""`vendor_params` from the project, `defaults:` and an action merge key by key.

A key set lower down replaces the same key from above; every other key above stays.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import ActionConfig, DefaultsConfig
from agent_actions.output.response.expander import ActionExpander


def _expand(action_params: dict | None, default_params: dict | None) -> dict:
    action = {"name": "a1", "intent": "i", "prompt": "p"}
    if action_params is not None:
        action["vendor_params"] = action_params
    defaults = {"model_vendor": "anthropic", "model_name": "m", "api_key": "k"}
    if default_params is not None:
        defaults["vendor_params"] = default_params
    expanded = ActionExpander.expand_actions_to_agents(
        {"name": "wf", "actions": [action], "defaults": defaults}
    )
    return expanded["wf"][0]


class TestDefaultsAndAction:
    def test_an_action_key_replaces_the_default_key_and_keeps_the_rest(self):
        agent = _expand(
            {"thinking": {"type": "disabled"}},
            {"thinking": {"type": "enabled", "budget_tokens": 1024}, "top_k": 5},
        )

        assert agent["vendor_params"] == {"thinking": {"type": "disabled"}, "top_k": 5}

    def test_the_defaults_reach_an_action_that_sets_none(self):
        assert _expand(None, {"top_k": 5})["vendor_params"] == {"top_k": 5}

    def test_an_action_alone_keeps_its_own(self):
        assert _expand({"top_k": 5}, None)["vendor_params"] == {"top_k": 5}

    def test_neither_leaves_the_key_out(self):
        assert "vendor_params" not in _expand(None, None)


def _manager(default_agent_config: dict | None) -> ConfigManager:
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = (
        {"default_agent_config": default_agent_config} if default_agent_config else {}
    )
    manager.tool_path = None
    manager.agent_configs = {}
    return manager


class TestProjectDefaultAgentConfig:
    def test_an_agent_key_replaces_the_project_key_and_keeps_the_rest(self):
        manager = _manager({"vendor_params": {"seed": 1, "top_k": 5}})

        manager.merge_agent_configs(
            [{"agent_type": "a1", "chunk_config": {}, "vendor_params": {"seed": 2}}]
        )

        assert manager.agent_configs["a1"].vendor_params == {"seed": 2, "top_k": 5}

    def test_the_project_value_reaches_an_agent_that_sets_none(self):
        manager = _manager({"vendor_params": {"seed": 1}})

        manager.merge_agent_configs([{"agent_type": "a1", "chunk_config": {}}])

        assert manager.agent_configs["a1"].vendor_params == {"seed": 1}


@pytest.mark.parametrize("model", [ActionConfig, DefaultsConfig])
def test_a_value_that_is_not_a_mapping_is_refused(model):
    fields = {"name": "a1", "intent": "i"} if model is ActionConfig else {}

    with pytest.raises(ValidationError, match="vendor_params"):
        model.model_validate({**fields, "vendor_params": ["thinking"]})

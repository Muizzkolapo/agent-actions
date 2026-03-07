"""Tests for config_fields mutable-default and deep-copy safety."""

from agent_actions.output.response.config_fields import (
    SIMPLE_CONFIG_FIELDS,
    inherit_simple_fields,
)
from agent_actions.output.response.expander import ActionExpander


class TestMutableDefaults:
    """Verify that mutable defaults cannot leak state across agents."""

    def test_constraints_default_is_immutable(self):
        """constraints default must be a tuple so accidental mutation fails fast."""
        assert isinstance(SIMPLE_CONFIG_FIELDS["constraints"], tuple)

    def test_inherit_deep_copies_list_from_action(self):
        """Lists coming from action config must be independent copies."""
        shared_list = ["no_pii"]
        action = {"constraints": shared_list}
        agent_a: dict = {}
        agent_b: dict = {}

        inherit_simple_fields(agent_a, action, {})
        inherit_simple_fields(agent_b, action, {})

        # Mutating one agent's constraints must not affect the other
        agent_a["constraints"].append("extra")
        assert "extra" not in agent_b["constraints"]
        assert "extra" not in shared_list

    def test_inherit_deep_copies_dict_from_defaults(self):
        """Dicts coming from defaults must be independent copies."""
        shared_dict = {"retry": {"max_retries": 3, "delay": 1}}
        defaults = {"retry": shared_dict["retry"]}
        agent_a: dict = {}
        agent_b: dict = {}

        inherit_simple_fields(agent_a, {}, defaults)
        inherit_simple_fields(agent_b, {}, defaults)

        agent_a["retry"]["max_retries"] = 99
        assert agent_b["retry"]["max_retries"] == 3

    def test_inherit_uses_tuple_default_when_no_override(self):
        """When neither action nor defaults provide constraints, the tuple default is used."""
        agent: dict = {}
        inherit_simple_fields(agent, {}, {})
        # Tuple default — immutable, no cross-agent risk
        assert agent["constraints"] == ()

    def test_inherit_scalar_values_unchanged(self):
        """Scalars (str, int, bool, None) should pass through without copy overhead."""
        action = {"model_vendor": "openai", "temperature": 0.7, "json_mode": False}
        agent: dict = {}
        inherit_simple_fields(agent, action, {})

        assert agent["model_vendor"] == "openai"
        assert agent["temperature"] == 0.7
        assert agent["json_mode"] is False


class TestIsOperationalFromConfig:
    """Verify is_operational is respected from action/defaults config."""

    def test_is_operational_false_from_action(self):
        """Action-level is_operational: false must propagate to agent."""
        action = {
            "name": "disabled_action",
            "model_vendor": "openai",
            "model_name": "gpt-4o",
            "api_key": "test-key",
        }
        defaults = {}
        agent = {"agent_type": "disabled_action", "name": "disabled_action"}

        result = ActionExpander._create_agent_from_action(
            {**action, "is_operational": False}, defaults, agent, lambda x: x
        )
        assert result["is_operational"] is False

    def test_is_operational_true_by_default(self):
        """Without explicit config, is_operational defaults to True."""
        action = {
            "name": "enabled_action",
            "model_vendor": "openai",
            "model_name": "gpt-4o",
            "api_key": "test-key",
        }
        defaults = {}
        agent = {"agent_type": "enabled_action", "name": "enabled_action"}

        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["is_operational"] is True

    def test_is_operational_false_from_defaults(self):
        """Defaults-level is_operational: false must propagate when action doesn't override."""
        action = {
            "name": "default_disabled",
            "model_vendor": "openai",
            "model_name": "gpt-4o",
            "api_key": "test-key",
        }
        defaults = {"is_operational": False}
        agent = {"agent_type": "default_disabled", "name": "default_disabled"}

        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["is_operational"] is False

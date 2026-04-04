"""Tests for runtime field propagation through the expander pipeline.

Issue #1050: Action-level runtime fields (anthropic_version,
enable_prompt_caching, max_execution_time, where_clause, enable_caching)
must survive expansion and appear in the final agent dict.
"""

import pytest

from agent_actions.output.response.config_fields import inherit_simple_fields
from agent_actions.output.response.expander import ActionExpander


def _minimal_action(**overrides):
    """Return a minimal valid action dict with optional overrides."""
    base = {
        "name": "test_action",
        "model_vendor": "openai",
        "model_name": "gpt-4o",
        "api_key": "test-key",
    }
    base.update(overrides)
    return base


def _make_agent(action, defaults=None):
    """Run _create_agent_from_action with minimal boilerplate."""
    defaults = defaults or {}
    agent = {"agent_type": action["name"], "name": action["name"]}
    return ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)


class TestRuntimeFieldPropagation:
    """Action-level runtime fields must flow through expander to agent dict."""

    @pytest.mark.parametrize(
        "field,value",
        [
            ("anthropic_version", "2023-06-01"),
            ("enable_prompt_caching", True),
            ("max_execution_time", 600),
            ("where_clause", {"clause": "status = 'active'"}),
            ("enable_caching", True),
        ],
    )
    def test_action_field_propagates_to_agent(self, field, value):
        """Value set on action YAML appears in final agent dict."""
        action = _minimal_action(**{field: value})
        result = _make_agent(action)
        assert result[field] == value

    def test_fields_default_when_absent(self):
        """Fields not set in action or defaults get their hardcoded default."""
        action = _minimal_action()
        result = _make_agent(action)
        # Optional fields default to None
        for field in [
            "anthropic_version",
            "enable_prompt_caching",
            "where_clause",
        ]:
            assert result[field] is None, f"{field} should default to None"
        # Fields with non-None defaults must match AgentConfig expectations
        assert result["enable_caching"] is True, "enable_caching should default to True"
        assert result["max_execution_time"] == 300, "max_execution_time should default to 300"

    def test_defaults_level_inheritance(self):
        """Fields set in defaults propagate when action omits them."""
        action = _minimal_action()
        defaults = {
            "anthropic_version": "2023-06-01",
            "enable_prompt_caching": True,
            "max_execution_time": 300,
            "where_clause": {"clause": "active = 1"},
            "enable_caching": True,
        }
        result = _make_agent(action, defaults)

        assert result["anthropic_version"] == "2023-06-01"
        assert result["enable_prompt_caching"] is True
        assert result["max_execution_time"] == 300
        assert result["where_clause"] == {"clause": "active = 1"}
        assert result["enable_caching"] is True

    def test_action_overrides_defaults(self):
        """Action-level value wins over defaults-level value."""
        defaults = {
            "anthropic_version": "2023-01-01",
            "max_execution_time": 100,
            "enable_caching": False,
        }
        action = _minimal_action(
            anthropic_version="2024-01-01",
            max_execution_time=600,
            enable_caching=True,
        )
        result = _make_agent(action, defaults)

        assert result["anthropic_version"] == "2024-01-01"
        assert result["max_execution_time"] == 600
        assert result["enable_caching"] is True


class TestEndToEndPropagation:
    """Integration tests through expand_actions_to_agents (full pipeline)."""

    RUNTIME_FIELDS = {
        "anthropic_version": "2023-06-01",
        "enable_prompt_caching": True,
        "max_execution_time": 600,
        "where_clause": {"clause": "status = 'active'"},
        "enable_caching": True,
    }

    def test_non_versioned_action_propagates_fields(self):
        """Runtime fields survive the full expand_actions_to_agents path."""
        config = {
            "name": "test_workflow",
            "actions": [_minimal_action(**self.RUNTIME_FIELDS)],
            "defaults": {},
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agent = result["test_workflow"][0]
        for field, value in self.RUNTIME_FIELDS.items():
            assert agent[field] == value, f"{field} not propagated end-to-end"

    def test_versioned_action_propagates_fields(self):
        """Runtime fields survive expansion through the versioned path."""
        action = _minimal_action(
            **self.RUNTIME_FIELDS,
            versions={"param": "i", "range": [1, 2]},
        )
        config = {
            "name": "test_workflow",
            "actions": [action],
            "defaults": {},
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]
        assert len(agents) == 2
        for agent in agents:
            for field, value in self.RUNTIME_FIELDS.items():
                assert agent[field] == value, (
                    f"{field} not propagated for versioned agent {agent['name']}"
                )

    def test_defaults_propagate_end_to_end(self):
        """Defaults-level runtime fields propagate through the full pipeline."""
        config = {
            "name": "test_workflow",
            "actions": [_minimal_action()],
            "defaults": self.RUNTIME_FIELDS,
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agent = result["test_workflow"][0]
        for field, value in self.RUNTIME_FIELDS.items():
            assert agent[field] == value, f"{field} not inherited from defaults"


class TestInheritSimpleFieldsRuntime:
    """Unit tests for inherit_simple_fields with the new runtime fields."""

    def test_runtime_fields_in_simple_config(self):
        """All 6 runtime fields must be present in SIMPLE_CONFIG_FIELDS."""
        from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS

        for field in [
            "anthropic_version",
            "enable_prompt_caching",
            "max_execution_time",
            "where_clause",
            "enable_caching",
        ]:
            assert field in SIMPLE_CONFIG_FIELDS, f"{field} missing from SIMPLE_CONFIG_FIELDS"

    def test_where_clause_dict_is_deep_copied(self):
        """where_clause dict must be deep-copied to prevent cross-agent mutation."""
        shared = {"clause": "x = 1"}
        action = {"where_clause": shared}
        agent_a: dict = {}
        agent_b: dict = {}

        inherit_simple_fields(agent_a, action, {})
        inherit_simple_fields(agent_b, action, {})

        agent_a["where_clause"]["clause"] = "MUTATED"
        assert agent_b["where_clause"]["clause"] == "x = 1"
        assert shared["clause"] == "x = 1"

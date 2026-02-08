"""Tests for configuration hierarchy resolution (project → workflow → action)."""

import pytest
from agent_actions.output.response.expander import ActionExpander


HIERARCHY_CASES = [
    pytest.param(
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "PROJECT_KEY"},
        {"name": "test_action", "intent": "Test action with no overrides"},
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "PROJECT_KEY"},
        id="project_only",
    ),
    pytest.param(
        {"model_vendor": "anthropic", "model_name": "claude-3-5-sonnet", "api_key": "PROJECT_KEY"},
        {"name": "test_action", "intent": "Test"},
        {"model_vendor": "anthropic", "model_name": "claude-3-5-sonnet", "api_key": "PROJECT_KEY"},
        id="workflow_overrides",
    ),
    pytest.param(
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"},
        {
            "name": "test_action",
            "intent": "Test",
            "model_vendor": "anthropic",
            "model_name": "claude-3-5-sonnet",
        },
        {"model_vendor": "anthropic", "model_name": "claude-3-5-sonnet", "api_key": "DEFAULT_KEY"},
        id="action_overrides_all",
    ),
    pytest.param(
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"},
        {"name": "test_action", "intent": "Test", "model_name": "gpt-4o-mini"},
        {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "DEFAULT_KEY"},
        id="partial_overrides",
    ),
    pytest.param(
        {"model_vendor": "openai", "api_key": "PROJECT_KEY"},
        {"name": "test_action", "intent": "Test", "model_name": "gpt-4o-mini"},
        {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "PROJECT_KEY"},
        id="three_levels_different_fields",
    ),
    pytest.param(
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"},
        {"name": "test_action", "intent": "Test"},
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"},
        id="missing_fields_use_defaults",
    ),
    pytest.param(
        {},
        {
            "name": "test_action",
            "intent": "Test",
            "model_vendor": "anthropic",
            "model_name": "claude-3-5-sonnet",
            "api_key": "ACTION_KEY",
        },
        {"model_vendor": "anthropic", "model_name": "claude-3-5-sonnet", "api_key": "ACTION_KEY"},
        id="empty_defaults_with_action_values",
    ),
]


class TestActionExpanderHierarchy:
    """Test 3-level configuration hierarchy resolution."""

    @pytest.mark.parametrize("defaults,action,expected", HIERARCHY_CASES)
    def test_config_hierarchy(self, defaults, action, expected):
        """Test that configuration hierarchy resolves correctly."""
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        for key, value in expected.items():
            assert result[key] == value, f"Field '{key}': expected {value!r}, got {result[key]!r}"

    def test_other_fields_inherit_correctly(self):
        """Test that other fields like json_mode inherit properly."""
        defaults = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "DEFAULT_KEY",
            "json_mode": True,
            "granularity": "record",
        }
        action = {"name": "test_action", "intent": "Test"}
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "openai"
        assert result["model_name"] == "gpt-4"
        assert result.get("json_mode") == True
        assert result.get("granularity") == "Record"

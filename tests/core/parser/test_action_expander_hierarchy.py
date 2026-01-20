"""Tests for configuration hierarchy resolution (project → workflow → action)."""

import pytest
from agent_actions.output.response.action_expander import ActionExpander


class TestActionExpanderHierarchy:
    """Test 3-level configuration hierarchy resolution."""

    def test_project_only_config(self):
        """Test all actions inherit from project-level config."""
        defaults = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "PROJECT_KEY"}
        action = {"name": "test_action", "intent": "Test action with no overrides"}
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "openai"
        assert result["model_name"] == "gpt-4"
        assert result["api_key"] == "PROJECT_KEY"

    def test_workflow_overrides_project(self):
        """Test workflow defaults override project settings."""
        defaults = {
            "model_vendor": "anthropic",
            "model_name": "claude-3-5-sonnet",
            "api_key": "PROJECT_KEY",
        }
        action = {"name": "test_action", "intent": "Test"}
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "anthropic"
        assert result["model_name"] == "claude-3-5-sonnet"
        assert result["api_key"] == "PROJECT_KEY"

    def test_action_overrides_all(self):
        """Test action-level config has highest precedence."""
        defaults = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"}
        action = {
            "name": "test_action",
            "intent": "Test",
            "model_vendor": "anthropic",
            "model_name": "claude-3-5-sonnet",
        }
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "anthropic"
        assert result["model_name"] == "claude-3-5-sonnet"
        assert result["api_key"] == "DEFAULT_KEY"

    def test_partial_overrides(self):
        """Test that only specified fields are overridden."""
        defaults = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"}
        action = {"name": "test_action", "intent": "Test", "model_name": "gpt-4o-mini"}
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "openai"
        assert result["model_name"] == "gpt-4o-mini"
        assert result["api_key"] == "DEFAULT_KEY"

    def test_three_levels_different_fields(self):
        """Test complex merge: different fields from each level."""
        defaults = {"model_vendor": "openai", "api_key": "PROJECT_KEY"}
        action = {"name": "test_action", "intent": "Test", "model_name": "gpt-4o-mini"}
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "openai"
        assert result["model_name"] == "gpt-4o-mini"
        assert result["api_key"] == "PROJECT_KEY"

    def test_missing_fields_use_defaults(self):
        """Test that missing fields fallback to defaults."""
        defaults = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"}
        action = {"name": "test_action", "intent": "Test"}
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "openai"
        assert result["model_name"] == "gpt-4"
        assert result["api_key"] == "DEFAULT_KEY"

    def test_empty_defaults_with_action_values(self):
        """Test action values work when defaults are empty."""
        defaults = {}
        action = {
            "name": "test_action",
            "intent": "Test",
            "model_vendor": "anthropic",
            "model_name": "claude-3-5-sonnet",
            "api_key": "ACTION_KEY",
        }
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "anthropic"
        assert result["model_name"] == "claude-3-5-sonnet"
        assert result["api_key"] == "ACTION_KEY"

    def test_other_fields_inherit_correctly(self):
        """Test that other fields like json_mode, few_shot inherit properly."""
        defaults = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "DEFAULT_KEY",
            "json_mode": True,
            "granularity": "record",
            "few_shot": 3,
        }
        action = {"name": "test_action", "intent": "Test", "few_shot": 5}
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "openai"
        assert result["model_name"] == "gpt-4"
        assert result.get("json_mode") == True
        assert result.get("granularity") == "Record"
        assert result.get("few_shot") == 5

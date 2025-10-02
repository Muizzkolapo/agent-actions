"""Tests for configuration hierarchy resolution (project → workflow → action)."""

import pytest
from agent_actions.core.parser.action_expander import ActionExpander


class TestActionExpanderHierarchy:
    """Test 3-level configuration hierarchy resolution."""

    def test_project_only_config(self):
        """Test all actions inherit from project-level config."""
        # Simulate: project config merged into defaults
        defaults = {
            'model_vendor': 'openai',
            'model_name': 'gpt-4',
            'api_key': 'PROJECT_KEY'
        }

        action = {
            'name': 'test_action',
            'intent': 'Test action with no overrides'
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, lambda x: x
        )

        # Should inherit all from project/defaults
        assert result['model_vendor'] == 'openai'
        assert result['model_name'] == 'gpt-4'
        assert result['api_key'] == 'PROJECT_KEY'

    def test_workflow_overrides_project(self):
        """Test workflow defaults override project settings."""
        # In real usage: project config + workflow defaults merged
        # Workflow values take precedence when both present
        defaults = {
            'model_vendor': 'anthropic',  # From workflow (overrides project)
            'model_name': 'claude-3-5-sonnet',  # From workflow (overrides project)
            'api_key': 'PROJECT_KEY'  # From project (not overridden)
        }

        action = {
            'name': 'test_action',
            'intent': 'Test'
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, lambda x: x
        )

        # Should use workflow overrides
        assert result['model_vendor'] == 'anthropic'
        assert result['model_name'] == 'claude-3-5-sonnet'
        assert result['api_key'] == 'PROJECT_KEY'

    def test_action_overrides_all(self):
        """Test action-level config has highest precedence."""
        defaults = {
            'model_vendor': 'openai',
            'model_name': 'gpt-4',
            'api_key': 'DEFAULT_KEY'
        }

        action = {
            'name': 'test_action',
            'intent': 'Test',
            'model_vendor': 'anthropic',  # Action override
            'model_name': 'claude-3-5-sonnet',  # Action override
            # api_key inherited
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, lambda x: x
        )

        # Action values take precedence
        assert result['model_vendor'] == 'anthropic'
        assert result['model_name'] == 'claude-3-5-sonnet'
        assert result['api_key'] == 'DEFAULT_KEY'  # Inherited

    def test_partial_overrides(self):
        """Test that only specified fields are overridden."""
        defaults = {
            'model_vendor': 'openai',
            'model_name': 'gpt-4',
            'api_key': 'DEFAULT_KEY'
        }

        action = {
            'name': 'test_action',
            'intent': 'Test',
            'model_name': 'gpt-4o-mini'  # Only override model
            # vendor and api_key inherited
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, lambda x: x
        )

        # Partial override works
        assert result['model_vendor'] == 'openai'  # Inherited
        assert result['model_name'] == 'gpt-4o-mini'  # Overridden
        assert result['api_key'] == 'DEFAULT_KEY'  # Inherited

    def test_three_levels_different_fields(self):
        """Test complex merge: different fields from each level."""
        # Simulates: project has api_key, workflow has vendor, action has model
        # In practice, all get merged into defaults before reaching action_expander
        defaults = {
            'model_vendor': 'openai',  # From workflow
            'api_key': 'PROJECT_KEY'  # From project
        }

        action = {
            'name': 'test_action',
            'intent': 'Test',
            'model_name': 'gpt-4o-mini'  # From action
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, lambda x: x
        )

        # Correctly merges all 3 levels
        assert result['model_vendor'] == 'openai'
        assert result['model_name'] == 'gpt-4o-mini'
        assert result['api_key'] == 'PROJECT_KEY'

    def test_missing_fields_use_defaults(self):
        """Test that missing fields fallback to defaults."""
        defaults = {
            'model_vendor': 'openai',
            'model_name': 'gpt-4',
            'api_key': 'DEFAULT_KEY'
        }

        action = {
            'name': 'test_action',
            'intent': 'Test',
            # All fields missing - should use defaults
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, lambda x: x
        )

        # Missing fields should use defaults
        assert result['model_vendor'] == 'openai'
        assert result['model_name'] == 'gpt-4'
        assert result['api_key'] == 'DEFAULT_KEY'

    def test_empty_defaults_with_action_values(self):
        """Test action values work when defaults are empty."""
        defaults = {}  # No defaults

        action = {
            'name': 'test_action',
            'intent': 'Test',
            'model_vendor': 'anthropic',
            'model_name': 'claude-3-5-sonnet',
            'api_key': 'ACTION_KEY'
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, lambda x: x
        )

        # Should use action values
        assert result['model_vendor'] == 'anthropic'
        assert result['model_name'] == 'claude-3-5-sonnet'
        assert result['api_key'] == 'ACTION_KEY'

    def test_other_fields_inherit_correctly(self):
        """Test that other fields like json_mode, few_shot inherit properly."""
        defaults = {
            'model_vendor': 'openai',
            'model_name': 'gpt-4',
            'api_key': 'DEFAULT_KEY',
            'json_mode': True,
            'granularity': 'record',
            'few_shot': 3
        }

        action = {
            'name': 'test_action',
            'intent': 'Test',
            'few_shot': 5  # Override just this
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, lambda x: x
        )

        # Core fields inherited
        assert result['model_vendor'] == 'openai'
        assert result['model_name'] == 'gpt-4'

        # Other fields inherited except overridden one
        assert result.get('json_mode') == True
        assert result.get('granularity') == 'Record'  # Capitalized in ActionExpander
        assert result.get('use_few_shot_samples') == 5  # Overridden

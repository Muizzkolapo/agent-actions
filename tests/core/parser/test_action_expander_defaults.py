"""Tests for ActionExpander defaults inheritance behavior."""

import pytest
from agent_actions.core.parser.action_expander import ActionExpander


class TestActionExpanderDefaults:
    """Test defaults inheritance in ActionExpander."""

    def test_drops_observe_inherit_from_defaults(self):
        """Test that drops and observe fields inherit from defaults."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with no drops/observe',
            'vendor': 'openai',
            'model': 'gpt-4o-mini',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt'
        }

        defaults = {
            'drops': ['internal_id', 'temp_metadata'],
            'observe': ['user_id', 'request_id', 'timestamp']
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should inherit drops and observe from defaults
        assert result['remove_collection'] == ['internal_id', 'temp_metadata']
        assert result['side_collection'] == ['user_id', 'request_id', 'timestamp']

    def test_action_level_drops_observe_override_defaults(self):
        """Test that action-level drops/observe completely override defaults."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with own drops/observe',
            'vendor': 'openai',
            'model': 'gpt-4o-mini',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt',
            'drops': ['action_field'],
            'observe': ['action_metadata']
        }

        defaults = {
            'drops': ['default_field'],
            'observe': ['default_metadata']
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should use action-level values, not defaults
        assert result['remove_collection'] == ['action_field']
        assert result['side_collection'] == ['action_metadata']

    def test_empty_action_level_drops_observe_override_defaults(self):
        """Test that empty action-level drops/observe still override defaults."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with empty drops/observe',
            'vendor': 'openai',
            'model': 'gpt-4o-mini',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt',
            'drops': [],
            'observe': []
        }

        defaults = {
            'drops': ['default_field'],
            'observe': ['default_metadata']
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should use empty action-level values, not defaults
        assert result['remove_collection'] == []
        assert result['side_collection'] == []

    def test_no_defaults_drops_observe_uses_empty_lists(self):
        """Test that when no defaults are provided, empty lists are used."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with no defaults',
            'vendor': 'openai',
            'model': 'gpt-4o-mini',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt'
        }

        defaults = {}  # No drops or observe in defaults

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should use empty lists
        assert result['remove_collection'] == []
        assert result['side_collection'] == []

    def test_partial_defaults_inheritance(self):
        """Test inheritance when only one of drops/observe is in defaults."""
        action = {
            'name': 'test_action',
            'intent': 'Test partial defaults',
            'vendor': 'openai',
            'model': 'gpt-4o-mini',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt'
        }

        defaults = {
            'drops': ['default_drop'],
            # No 'observe' in defaults
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should inherit drops, use empty list for observe
        assert result['remove_collection'] == ['default_drop']
        assert result['side_collection'] == []

    def test_tool_action_processes_drops_observe(self):
        """Test that tool actions (record level) still process drops/observe."""
        action = {
            'name': 'test_tool',
            'kind': 'tool',
            'impl': 'module.function',
            'intent': 'Test tool action'
        }

        defaults = {
            'drops': ['default_field'],
            'observe': ['default_metadata']
        }

        agent = {'agent_type': 'test_tool', 'name': 'test_tool'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Regular tool actions should still process drops/observe
        assert result['side_collection'] == ['default_metadata']
        assert result['remove_collection'] == ['default_field']

    def test_file_level_tool_action_skips_drops_observe(self):
        """Test that file-level tool actions skip drops/observe processing."""
        action = {
            'name': 'test_tool',
            'kind': 'tool',
            'impl': 'module.function',
            'granularity': 'file',
            'intent': 'Test file-level tool action'
        }

        defaults = {
            'drops': ['default_field'],
            'observe': ['default_metadata'],
            'granularity': 'record'  # Default granularity
        }

        agent = {'agent_type': 'test_tool', 'name': 'test_tool'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # File-level tool actions should not have side_collection or remove_collection
        assert 'side_collection' not in result
        assert 'remove_collection' not in result
        assert result['granularity'] == 'File'

    def test_other_defaults_still_work(self):
        """Test that other defaults (vendor, model, etc.) still work with drops/observe."""
        action = {
            'name': 'test_action',
            'intent': 'Test other defaults',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt'
            # No vendor/model specified
        }

        defaults = {
            'vendor': 'openai',
            'model': 'gpt-4o-mini',
            'json_mode': True,
            'drops': ['default_drop'],
            'observe': ['default_observe']
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should inherit all defaults
        assert result['model_vendor'] == 'openai'
        assert result['model_name'] == 'gpt-4o-mini'
        assert result['json_mode'] == True
        assert result['remove_collection'] == ['default_drop']
        assert result['side_collection'] == ['default_observe']

    def test_template_replacement_in_drops_observe_from_defaults(self):
        """Test that template replacement works for drops/observe inherited from defaults."""
        action = {
            'name': 'test_action',
            'intent': 'Test template replacement',
            'vendor': 'openai',
            'model': 'gpt-4o-mini',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt'
        }

        defaults = {
            'drops': ['{{prefix}}_field'],
            'observe': ['{{prefix}}_metadata']
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}

        # Mock template replacer that replaces {{prefix}} with 'test'
        def template_replacer(value):
            if isinstance(value, list):
                return [item.replace('{{prefix}}', 'test') if isinstance(item, str) else item for item in value]
            elif isinstance(value, str):
                return value.replace('{{prefix}}', 'test')
            return value

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should apply template replacement to inherited values
        assert result['remove_collection'] == ['test_field']
        assert result['side_collection'] == ['test_metadata']


class TestActionExpanderFullWorkflow:
    """Test full workflow expansion with defaults."""

    def test_expand_actions_to_agents_with_drops_observe_defaults(self):
        """Test full workflow expansion with drops/observe in defaults."""
        workflow_config = {
            'name': 'test_workflow',
            'description': 'Test workflow',
            'version': '2.0.0',
            'defaults': {
                'vendor': 'openai',
                'model': 'gpt-4o-mini',
                'drops': ['internal_id', 'temp_data'],
                'observe': ['user_id', 'session_id']
            },
            'actions': [
                {
                    'name': 'action1',
                    'intent': 'First action',
                    'schema': {'output': 'string'},
                    'prompt': 'Process data'
                },
                {
                    'name': 'action2',
                    'intent': 'Second action',
                    'schema': {'output': 'string'},
                    'drops': ['other_field'],
                    'observe': ['correlation_id'],
                    'prompt': 'Process more data'
                }
            ],
            'plan': [
                'action1',
                'action2 <- action1'
            ]
        }

        result = ActionExpander.expand_actions_to_agents(workflow_config)

        agents = result['test_workflow']

        # First action should inherit defaults
        action1 = next(a for a in agents if a['name'] == 'action1')
        assert action1['remove_collection'] == ['internal_id', 'temp_data']
        assert action1['side_collection'] == ['user_id', 'session_id']

        # Second action should use its own values
        action2 = next(a for a in agents if a['name'] == 'action2')
        assert action2['remove_collection'] == ['other_field']
        assert action2['side_collection'] == ['correlation_id']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
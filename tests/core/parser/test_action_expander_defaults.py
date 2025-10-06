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
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
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

    def test_action_level_drops_observe_extend_defaults(self):
        """Test that action-level drops/observe extend defaults additively."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with own drops/observe',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
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

        # Should combine defaults + action-level values
        assert result['remove_collection'] == ['default_field', 'action_field']
        assert result['side_collection'] == ['default_metadata', 'action_metadata']

    def test_empty_action_level_drops_observe_with_defaults(self):
        """Test that empty action-level drops/observe combined with defaults results in just defaults."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with empty drops/observe',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
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

        # Should use defaults since empty + defaults = defaults
        assert result['remove_collection'] == ['default_field']
        assert result['side_collection'] == ['default_metadata']

    def test_no_defaults_drops_observe_uses_empty_lists(self):
        """Test that when no defaults are provided, empty lists are used."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with no defaults',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
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
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
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
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
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
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
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

    def test_additive_behavior_with_deduplication(self):
        """Test that additive behavior removes duplicates while preserving order."""
        action = {
            'name': 'test_action',
            'intent': 'Test deduplication',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt',
            'drops': ['shared_field', 'action_field'],
            'observe': ['shared_metadata', 'action_metadata']
        }

        defaults = {
            'drops': ['default_field', 'shared_field'],
            'observe': ['default_metadata', 'shared_metadata']
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should combine with deduplication (defaults first, then unique action fields)
        assert result['remove_collection'] == ['default_field', 'shared_field', 'action_field']
        assert result['side_collection'] == ['default_metadata', 'shared_metadata', 'action_metadata']


class TestActionExpanderFullWorkflow:
    """Test full workflow expansion with defaults."""

    def test_expand_actions_to_agents_with_drops_observe_defaults(self):
        """Test full workflow expansion with drops/observe in defaults."""
        workflow_config = {
            'name': 'test_workflow',
            'description': 'Test workflow',
            'version': '2.0.0',
            'defaults': {
                'model_vendor': 'openai',
                'model_name': 'gpt-4o-mini',
                'api_key': 'OPENAI_API_KEY',
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

        # Second action should combine defaults + its own values
        action2 = next(a for a in agents if a['name'] == 'action2')
        assert action2['remove_collection'] == ['internal_id', 'temp_data', 'other_field']
        assert action2['side_collection'] == ['user_id', 'session_id', 'correlation_id']


class TestActionExpanderInterceptors:
    """Test interceptors field mapping in ActionExpander."""

    def test_action_with_interceptors_maps_correctly(self):
        """Test that action-level interceptors are mapped to agent config."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with interceptors',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt',
            'interceptors': [
                {
                    'type': 'validation',
                    'validator_function': 'test.validator',
                    'validator_args': {'expected': 10},
                    'on_failure': 'retry'
                },
                {
                    'type': 'reprompt',
                    'strategy': 'llm',
                    'max_attempts': 3
                }
            ]
        }

        defaults = {}
        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should map interceptors field correctly
        assert 'interceptors' in result
        assert len(result['interceptors']) == 2
        assert result['interceptors'][0]['type'] == 'validation'
        assert result['interceptors'][0]['validator_function'] == 'test.validator'
        assert result['interceptors'][1]['type'] == 'reprompt'
        assert result['interceptors'][1]['strategy'] == 'llm'

    def test_action_without_interceptors_has_no_interceptors_field(self):
        """Test that actions without interceptors don't have interceptors field."""
        action = {
            'name': 'test_action',
            'intent': 'Test action without interceptors',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt'
        }

        defaults = {}
        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should not have interceptors field when not specified
        assert 'interceptors' not in result

    def test_empty_interceptors_list_not_mapped(self):
        """Test that empty interceptors list is not mapped."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with empty interceptors',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt',
            'interceptors': []
        }

        defaults = {}
        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should not map empty interceptors list
        assert 'interceptors' not in result

    def test_interceptors_with_defaults_and_other_fields(self):
        """Test that interceptors work alongside other field mappings."""
        action = {
            'name': 'test_action',
            'intent': 'Test comprehensive action',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt',
            'drops': ['temp_field'],
            'observe': ['tracking_id'],
            'interceptors': [
                {
                    'type': 'validation',
                    'validator_function': 'test.validator'
                }
            ]
        }

        defaults = {
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
            'drops': ['default_drop'],
            'observe': ['default_observe']
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should map all fields correctly
        assert result['model_vendor'] == 'openai'
        assert result['model_name'] == 'gpt-4o-mini'
        assert result['remove_collection'] == ['default_drop', 'temp_field']
        assert result['side_collection'] == ['default_observe', 'tracking_id']
        assert 'interceptors' in result
        assert len(result['interceptors']) == 1
        assert result['interceptors'][0]['type'] == 'validation'

    def test_full_workflow_with_interceptors(self):
        """Test complete workflow expansion with interceptors."""
        workflow_config = {
            'name': 'test_workflow',
            'description': 'Test workflow with interceptors',
            'version': '2.0.0',
            'defaults': {
                'model_vendor': 'openai',
                'model_name': 'gpt-4o-mini',
                'api_key': 'OPENAI_API_KEY'
            },
            'actions': [
                {
                    'name': 'validated_action',
                    'intent': 'Action with validation',
                    'schema': {'output': 'string'},
                    'prompt': 'Generate validated output',
                    'interceptors': [
                        {
                            'type': 'validation',
                            'validator_function': 'validators.test_validator',
                            'on_failure': 'retry'
                        },
                        {
                            'type': 'reprompt',
                            'strategy': 'llm',
                            'max_attempts': 3
                        }
                    ]
                },
                {
                    'name': 'regular_action',
                    'intent': 'Action without interceptors',
                    'schema': {'output': 'string'},
                    'prompt': 'Generate regular output'
                }
            ],
            'plan': ['validated_action', 'regular_action']
        }

        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result['test_workflow']

        # Find the validated action
        validated_action = next(a for a in agents if a['name'] == 'validated_action')
        assert 'interceptors' in validated_action
        assert len(validated_action['interceptors']) == 2

        # Find the regular action
        regular_action = next(a for a in agents if a['name'] == 'regular_action')
        assert 'interceptors' not in regular_action


class TestActionExpanderPromptDebug:
    """Test prompt_debug inheritance and action-level override."""

    def test_prompt_debug_inherits_from_defaults(self):
        """Test that prompt_debug inherits from defaults."""
        action = {
            'name': 'test_action',
            'intent': 'Test action',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt'
            # No prompt_debug specified
        }

        defaults = {
            'prompt_debug': True
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should inherit prompt_debug from defaults
        assert result['prompt_debug'] is True

    def test_prompt_debug_action_override(self):
        """Test that action-level prompt_debug overrides defaults."""
        action = {
            'name': 'test_action',
            'intent': 'Test action',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt',
            'prompt_debug': True  # Action-level override
        }

        defaults = {
            'prompt_debug': False  # Default is False
        }

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Action-level should override defaults
        assert result['prompt_debug'] is True

    def test_prompt_debug_defaults_to_false(self):
        """Test that prompt_debug defaults to False when not specified."""
        action = {
            'name': 'test_action',
            'intent': 'Test action',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'OPENAI_API_KEY',
            'schema': {'output': 'string'},
            'prompt': 'Test prompt'
            # No prompt_debug specified
        }

        defaults = {}  # No defaults either

        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should default to False
        assert result['prompt_debug'] is False

    def test_prompt_debug_in_loop_actions(self):
        """Test that prompt_debug works correctly in loop-expanded actions."""
        workflow_config = {
            'name': 'test_workflow',
            'defaults': {
                'model_vendor': 'openai',
                'model_name': 'gpt-4o-mini',
                'api_key': 'OPENAI_API_KEY',
                'prompt_debug': True  # Default prompt_debug enabled
            },
            'actions': [
                {
                    'name': 'looped_action',
                    'intent': 'Test loop',
                    'schema': {'output': 'string'},
                    'prompt': 'Loop iteration ${i}',
                    'loop': {
                        'param': 'i',
                        'range': [1, 3]
                    }
                }
            ],
            'plan': [
                'looped_action'
            ]
        }

        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result['test_workflow']

        # All loop iterations should have prompt_debug from defaults
        assert len(agents) == 3
        for agent in agents:
            assert agent['prompt_debug'] is True
            assert agent['is_loop_agent'] is True

    def test_prompt_debug_in_loop_with_action_override(self):
        """Test that action-level prompt_debug overrides defaults in loop."""
        workflow_config = {
            'name': 'test_workflow',
            'defaults': {
                'model_vendor': 'openai',
                'model_name': 'gpt-4o-mini',
                'api_key': 'OPENAI_API_KEY',
                'prompt_debug': False  # Default is False
            },
            'actions': [
                {
                    'name': 'looped_action',
                    'intent': 'Test loop',
                    'schema': {'output': 'string'},
                    'prompt': 'Loop iteration ${i}',
                    'prompt_debug': True,  # Action-level override
                    'loop': {
                        'param': 'i',
                        'range': [1, 2]
                    }
                }
            ],
            'plan': [
                'looped_action'
            ]
        }

        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result['test_workflow']

        # All loop iterations should have prompt_debug from action, not defaults
        assert len(agents) == 2
        for agent in agents:
            assert agent['prompt_debug'] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
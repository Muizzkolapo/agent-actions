"""Tests for automated config field inheritance system."""
import pytest
from agent_actions.response_processing.config_field_definitions import SIMPLE_CONFIG_FIELDS, inherit_simple_fields
from agent_actions.response_processing.action_expander import ActionExpander

class TestConfigFieldDefinitions:
    """Test the config_field_definitions module directly."""

    def test_simple_config_fields_contains_all_expected_fields(self):
        """Test that SIMPLE_CONFIG_FIELDS contains all expected fields."""
        expected_fields = {'model_vendor', 'model_name', 'api_key', 'run_mode', 'is_operational', 'json_mode', 'prompt_debug', 'few_shot'}
        assert set(SIMPLE_CONFIG_FIELDS.keys()) == expected_fields

    def test_default_values_have_correct_types(self):
        """Test that default values have correct types."""
        assert SIMPLE_CONFIG_FIELDS['model_vendor'] is None
        assert SIMPLE_CONFIG_FIELDS['model_name'] is None
        assert SIMPLE_CONFIG_FIELDS['api_key'] is None
        assert SIMPLE_CONFIG_FIELDS['run_mode'] == 'online'
        assert SIMPLE_CONFIG_FIELDS['is_operational'] is True
        assert SIMPLE_CONFIG_FIELDS['json_mode'] is True
        assert SIMPLE_CONFIG_FIELDS['prompt_debug'] is False
        assert SIMPLE_CONFIG_FIELDS['few_shot'] == 0

class TestInheritSimpleFields:
    """Test inherit_simple_fields() function behavior."""

    def test_inherits_from_defaults_when_not_in_action(self):
        """Test that fields inherit from defaults when not in action."""
        agent = {}
        action = {}
        defaults = {'model_vendor': 'openai', 'model_name': 'gpt-4'}
        inherit_simple_fields(agent, action, defaults)
        assert agent['model_vendor'] == 'openai'
        assert agent['model_name'] == 'gpt-4'

    def test_action_overrides_defaults(self):
        """Test that action-level values override defaults."""
        agent = {}
        action = {'model_vendor': 'anthropic', 'json_mode': False}
        defaults = {'model_vendor': 'openai', 'json_mode': True}
        inherit_simple_fields(agent, action, defaults)
        assert agent['model_vendor'] == 'anthropic'
        assert agent['json_mode'] is False

    def test_uses_hardcoded_default_when_not_in_either(self):
        """Test that hardcoded defaults are used when not in action or defaults."""
        agent = {}
        action = {}
        defaults = {}
        inherit_simple_fields(agent, action, defaults)
        assert agent['json_mode'] is True
        assert agent['prompt_debug'] is False
        assert agent['run_mode'] == 'online'
        assert agent['few_shot'] == 0

    def test_all_simple_fields_inherited(self):
        """Test that all fields in SIMPLE_CONFIG_FIELDS are inherited."""
        agent = {}
        action = {}
        defaults = {'model_vendor': 'openai', 'model_name': 'gpt-4', 'api_key': 'test_key'}
        inherit_simple_fields(agent, action, defaults)
        for field in SIMPLE_CONFIG_FIELDS.keys():
            assert field in agent

    def test_inheritance_priority_order(self):
        """Test that inheritance follows correct priority: action > defaults > hardcoded."""
        agent = {}
        action = {'model_vendor': 'anthropic'}
        defaults = {'model_vendor': 'openai', 'model_name': 'gpt-4'}
        inherit_simple_fields(agent, action, defaults)
        assert agent['model_vendor'] == 'anthropic'
        assert agent['model_name'] == 'gpt-4'
        assert agent['json_mode'] is True

    def test_modifies_agent_dict_in_place(self):
        """Test that function modifies agent dict in-place."""
        agent = {'agent_type': 'test'}
        action = {'model_vendor': 'openai'}
        defaults = {}
        inherit_simple_fields(agent, action, defaults)
        assert agent['agent_type'] == 'test'
        assert 'model_vendor' in agent

class TestActionExpanderIntegration:
    """Test that ActionExpander correctly uses inherit_simple_fields()."""

    def test_action_expander_uses_inherit_simple_fields(self):
        """Test that ActionExpander._create_agent_from_action() uses inherit_simple_fields()."""
        action = {'name': 'test_action', 'model_vendor': 'openai', 'model_name': 'gpt-4', 'api_key': 'test_key', 'schema': {'output': 'string'}, 'prompt': 'Test prompt'}
        defaults = {'json_mode': False, 'few_shot': 5}
        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer, is_operational=True)
        assert result['model_vendor'] == 'openai'
        assert result['model_name'] == 'gpt-4'
        assert result['api_key'] == 'test_key'
        assert result['json_mode'] is False
        assert result['few_shot'] == 5
        assert result['prompt_debug'] is False

    def test_is_operational_from_plan_not_defaults(self):
        """Test that is_operational comes from plan parameter, not defaults."""
        action = {'name': 'test_action', 'model_vendor': 'openai', 'model_name': 'gpt-4', 'api_key': 'test_key', 'schema': {'output': 'string'}}
        defaults = {'is_operational': False}
        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer, is_operational=True)
        assert result['is_operational'] is True

    def test_complex_fields_still_work(self):
        """Test that complex fields (schema, prompt, etc.) are still handled correctly."""
        action = {'name': 'test_action', 'model_vendor': 'openai', 'model_name': 'gpt-4', 'api_key': 'test_key', 'schema': {'output': 'string'}, 'prompt': 'Test prompt with {variable}', 'observe': ['field1', 'field2'], 'drops': ['field3']}
        defaults = {}
        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)
        assert result['schema'] == {'output': 'string'}
        assert result['prompt'] == 'Test prompt with {variable}'
        assert result['observe'] == ['field1', 'field2']
        assert result['drops'] == ['field3']

    def test_json_mode_defaults_to_true(self):
        """Test that json_mode defaults to True (JSON-based system)."""
        action = {'name': 'test_action', 'model_vendor': 'openai', 'model_name': 'gpt-4', 'api_key': 'test_key', 'schema': {'output': 'string'}}
        defaults = {}
        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)
        assert result['json_mode'] is True

    def test_field_override_chain_works(self):
        """Test that field override chain works: action > defaults > hardcoded."""
        action = {'name': 'test_action', 'model_vendor': 'anthropic', 'model_name': 'claude-3', 'api_key': 'action_key', 'json_mode': False, 'few_shot': 10, 'schema': {'output': 'string'}}
        defaults = {'model_vendor': 'openai', 'model_name': 'gpt-4', 'api_key': 'default_key', 'json_mode': True, 'few_shot': 5}
        agent = {'agent_type': 'test_action', 'name': 'test_action'}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result['model_vendor'] == 'anthropic'
        assert result['model_name'] == 'claude-3'
        assert result['api_key'] == 'action_key'
        assert result['json_mode'] is False
        assert result['few_shot'] == 10

    def test_extensibility_adding_new_field_works(self):
        """Test that adding a new field to SIMPLE_CONFIG_FIELDS works without code changes."""
        original_fields = SIMPLE_CONFIG_FIELDS.copy()
        SIMPLE_CONFIG_FIELDS['new_test_field'] = 'test_default'
        try:
            agent = {}
            action = {'new_test_field': 'action_value'}
            defaults = {}
            inherit_simple_fields(agent, action, defaults)
            assert agent['new_test_field'] == 'action_value'
            agent2 = {}
            action2 = {}
            defaults2 = {'new_test_field': 'default_value'}
            inherit_simple_fields(agent2, action2, defaults2)
            assert agent2['new_test_field'] == 'default_value'
        finally:
            SIMPLE_CONFIG_FIELDS.clear()
            SIMPLE_CONFIG_FIELDS.update(original_fields)

class TestBackwardCompatibility:
    """Test that existing functionality still works after refactoring."""

    def test_full_workflow_expansion_works(self):
        """Test that full workflow expansion still works."""
        workflow_config = {'name': 'test_workflow', 'defaults': {'model_vendor': 'openai', 'model_name': 'gpt-4', 'api_key': 'test_key', 'json_mode': True, 'few_shot': 3}, 'actions': [{'name': 'action1', 'schema': {'output': 'string'}, 'prompt': 'Test prompt 1'}, {'name': 'action2', 'json_mode': False, 'few_shot': 5, 'schema': {'output': 'string'}, 'prompt': 'Test prompt 2'}], 'plan': ['action1', 'action2']}
        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result['test_workflow']
        assert len(agents) == 2
        action1 = agents[0]
        assert action1['model_vendor'] == 'openai'
        assert action1['model_name'] == 'gpt-4'
        assert action1['json_mode'] is True
        assert action1['few_shot'] == 3
        action2 = agents[1]
        assert action2['model_vendor'] == 'openai'
        assert action2['model_name'] == 'gpt-4'
        assert action2['json_mode'] is False
        assert action2['few_shot'] == 5
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
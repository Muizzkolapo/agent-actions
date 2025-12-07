"""Tests for format converter guard handling."""
import pytest
from agent_actions.response_processing.action_expander import ActionExpander
from agent_actions.errors import ValidationError  # New modular pattern!

class TestFormatConverterGuards:
    """Test guard handling in format converter."""

    def test_convert_sql_guard(self):
        """Test conversion of SQL-like guard expressions."""
        action = {'name': 'test_action', 'intent': 'Test action with SQL guard', 'guard': 'questionable != "Low Value"', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY'}
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)
        assert result.get('where_clause') is not None
        assert result['where_clause']['clause'] == 'questionable != "Low Value"'
        assert result['where_clause']['scope'] == 'item'
        assert result.get('conditional_clause') is None

    def test_convert_udf_guard(self):
        """Test conversion of UDF guard expressions."""
        action = {'name': 'test_action', 'intent': 'Test action with UDF guard', 'guard': 'udf:topic_to_quiz_pipeline.get_answer_length_flag_value', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY'}
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)
        assert result.get('conditional_clause') == 'topic_to_quiz_pipeline.get_answer_length_flag_value'
        assert result.get('where_clause') is None

    def test_convert_no_guard(self):
        """Test conversion when no guard is specified."""
        action = {'name': 'test_action', 'intent': 'Test action without guard', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY'}
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)
        assert result.get('conditional_clause') is None
        assert result.get('where_clause') is None

    def test_convert_complex_sql_guard(self):
        """Test conversion of complex SQL guard expressions."""
        action = {'name': 'test_action', 'intent': 'Test action with complex SQL guard', 'guard': 'questionable == "High Value" AND confidence > 0.8', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY'}
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)
        assert result['where_clause']['clause'] == 'questionable == "High Value" AND confidence > 0.8'
        assert result.get('conditional_clause') is None

    def test_convert_whitespace_udf_guard(self):
        """Test conversion of UDF guard with whitespace."""
        action = {'name': 'test_action', 'intent': 'Test action with whitespace UDF guard', 'guard': '  udf:  module.function  ', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY'}
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)
        assert result.get('conditional_clause') == 'module.function'
        assert result.get('where_clause') is None

    def test_convert_invalid_guard_raises_error(self):
        """Test that invalid guard expressions raise errors."""
        action = {'name': 'test_action', 'intent': 'Test action with invalid guard', 'guard': 'udf:invalid_format', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY'}
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x
        with pytest.raises(ValidationError, match='Invalid UDF expression format'):
            ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

    def test_convert_dangerous_udf_guard_raises_error(self):
        """Test that dangerous UDF expressions raise errors."""
        action = {'name': 'test_action', 'intent': 'Test action with dangerous UDF guard', 'guard': 'udf:module.__import__', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY'}
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x
        with pytest.raises(ValidationError, match='potentially dangerous pattern'):
            ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

    def test_convert_dangerous_sql_guard_raises_error(self):
        """Test that dangerous SQL expressions raise errors."""
        action = {'name': 'test_action', 'intent': 'Test action with dangerous SQL guard', 'guard': 'field == "value" AND exec("code")', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY'}
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x
        with pytest.raises(ValidationError, match='potentially dangerous pattern'):
            ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)

    def test_convert_tool_action_with_udf_guard(self):
        """Test conversion of tool action with UDF guard."""
        action = {'name': 'test_tool', 'kind': 'tool', 'impl': 'module.tool_function', 'intent': 'Test tool with UDF guard', 'guard': 'udf:validators.should_run_tool'}
        defaults = {}
        agent = {'agent_type': 'test_tool'}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(action, defaults, agent, template_replacer)
        assert result.get('conditional_clause') == 'validators.should_run_tool'
        assert result['model_vendor'] == 'tool'
        assert result.get('where_clause') is None
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
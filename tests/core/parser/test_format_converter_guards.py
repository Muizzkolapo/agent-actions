"""Tests for format converter guard handling."""

import pytest
from agent_actions.core.parser.format_converter import WorkflowFormatConverter


class TestFormatConverterGuards:
    """Test guard handling in format converter."""

    def test_convert_sql_guard(self):
        """Test conversion of SQL-like guard expressions."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with SQL guard',
            'guard': 'questionable != "Low Value"',
            'vendor': 'openai',
            'model': 'gpt-4o-mini'
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        result = WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should set where_clause for SQL guards
        assert result.get('where_clause') is not None
        assert result['where_clause']['clause'] == 'questionable != "Low Value"'
        assert result['where_clause']['scope'] == 'item'
        assert result.get('conditional_clause') is None

    def test_convert_udf_guard(self):
        """Test conversion of UDF guard expressions."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with UDF guard',
            'guard': 'udf:topic_to_quiz_pipeline.get_answer_length_flag_value',
            'vendor': 'openai',
            'model': 'gpt-4o-mini'
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        result = WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should set conditional_clause for UDF guards
        assert result.get('conditional_clause') == 'topic_to_quiz_pipeline.get_answer_length_flag_value'
        assert result.get('where_clause') is None

    def test_convert_no_guard(self):
        """Test conversion when no guard is specified."""
        action = {
            'name': 'test_action',
            'intent': 'Test action without guard',
            'vendor': 'openai',
            'model': 'gpt-4o-mini'
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        result = WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should not set either conditional field
        assert result.get('conditional_clause') is None
        assert result.get('where_clause') is None

    def test_convert_complex_sql_guard(self):
        """Test conversion of complex SQL guard expressions."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with complex SQL guard',
            'guard': 'questionable == "High Value" AND confidence > 0.8',
            'vendor': 'openai',
            'model': 'gpt-4o-mini'
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        result = WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

        assert result['where_clause']['clause'] == 'questionable == "High Value" AND confidence > 0.8'
        assert result.get('conditional_clause') is None

    def test_convert_whitespace_udf_guard(self):
        """Test conversion of UDF guard with whitespace."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with whitespace UDF guard',
            'guard': '  udf:  module.function  ',
            'vendor': 'openai',
            'model': 'gpt-4o-mini'
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        result = WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

        # Should trim whitespace from UDF expression
        assert result.get('conditional_clause') == 'module.function'
        assert result.get('where_clause') is None

    def test_convert_invalid_guard_raises_error(self):
        """Test that invalid guard expressions raise errors."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with invalid guard',
            'guard': 'udf:invalid_format',
            'vendor': 'openai',
            'model': 'gpt-4o-mini'
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        with pytest.raises(ValueError, match="Invalid UDF expression format"):
            WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

    def test_convert_dangerous_udf_guard_raises_error(self):
        """Test that dangerous UDF expressions raise errors."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with dangerous UDF guard',
            'guard': 'udf:module.__import__',
            'vendor': 'openai',
            'model': 'gpt-4o-mini'
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        with pytest.raises(ValueError, match="potentially dangerous pattern"):
            WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

    def test_convert_dangerous_sql_guard_raises_error(self):
        """Test that dangerous SQL expressions raise errors."""
        action = {
            'name': 'test_action',
            'intent': 'Test action with dangerous SQL guard',
            'guard': 'field == "value" AND exec("code")',
            'vendor': 'openai',
            'model': 'gpt-4o-mini'
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        with pytest.raises(ValueError, match="potentially dangerous pattern"):
            WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

    def test_convert_tool_action_with_udf_guard(self):
        """Test conversion of tool action with UDF guard."""
        action = {
            'name': 'test_tool',
            'kind': 'tool',
            'impl': 'module.tool_function',
            'intent': 'Test tool with UDF guard',
            'guard': 'udf:validators.should_run_tool',
        }

        # Setup test parameters
        defaults = {}
        agent = {'agent_type': 'test_tool'}
        template_replacer = lambda x: x

        result = WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, template_replacer)

        assert result.get('conditional_clause') == 'validators.should_run_tool'
        assert result['model_vendor'] == 'tool'
        assert result.get('where_clause') is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
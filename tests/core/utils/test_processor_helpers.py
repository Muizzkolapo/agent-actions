"""Tests for processor helper functions."""
import pytest
from unittest.mock import patch, MagicMock
from agent_actions.utilities.processor.processor_helpers import run_dynamic_agent, _should_skip_legacy_conditional, _should_skip_where_clause

class TestShouldSkipLegacyConditional:
    """Test the _should_skip_legacy_conditional helper function."""

    @patch('agent_actions.utilities.tooling.execute_user_defined_function')
    def test_skip_when_conditional_clause_returns_false(self, mock_execute_udf):
        """Test skipping when conditional clause evaluates to False."""
        mock_execute_udf.return_value = False
        agent_config = {'conditional_clause': 'validators.should_process'}
        context = {'data': 'test'}
        result = _should_skip_legacy_conditional(agent_config, context)
        assert result is True
        mock_execute_udf.assert_called_once_with('validators.should_process', context)

    @patch('agent_actions.utilities.tooling.execute_user_defined_function')
    def test_no_skip_when_conditional_clause_returns_true(self, mock_execute_udf):
        """Test not skipping when conditional clause evaluates to True."""
        mock_execute_udf.return_value = True
        agent_config = {'conditional_clause': 'validators.should_process'}
        context = {'data': 'test'}
        result = _should_skip_legacy_conditional(agent_config, context)
        assert result is False
        mock_execute_udf.assert_called_once_with('validators.should_process', context)

    def test_no_skip_when_no_conditional_clause(self):
        """Test not skipping when no conditional clause is present."""
        agent_config = {}
        context = {'data': 'test'}
        result = _should_skip_legacy_conditional(agent_config, context)
        assert result is False

    def test_no_skip_when_conditional_clause_empty(self):
        """Test not skipping when conditional clause is empty."""
        agent_config = {'conditional_clause': ''}
        context = {'data': 'test'}
        result = _should_skip_legacy_conditional(agent_config, context)
        assert result is False

    @patch('agent_actions.utilities.tooling.execute_user_defined_function')
    def test_case_insensitive_conditional_clause(self, mock_execute_udf):
        """Test that conditional clause is converted to lowercase."""
        mock_execute_udf.return_value = False
        agent_config = {'conditional_clause': 'VALIDATORS.SHOULD_PROCESS'}
        context = {'data': 'test'}
        result = _should_skip_legacy_conditional(agent_config, context)
        assert result is True
        mock_execute_udf.assert_called_once_with('validators.should_process', context)

class TestShouldSkipWhereClause:
    """Test the _should_skip_where_clause helper function."""

    @patch('agent_actions.response_processing.where_parser.get_global_filter')
    def test_skip_when_filter_returns_false(self, mock_get_filter):
        """Test skipping when filter condition evaluates to False."""
        mock_filter_service = MagicMock()
        mock_filter_service.filter_item.return_value = False
        mock_get_filter.return_value = mock_filter_service
        agent_config = {'where_clause': {'clause': 'should_keep_cluster == false', 'behavior': 'skip'}}
        context = {'should_keep_cluster': True}
        result = _should_skip_where_clause(agent_config, context)
        assert result is True
        mock_filter_service.filter_item.assert_called_once_with(context, 'should_keep_cluster == false')

    @patch('agent_actions.response_processing.where_parser.get_global_filter')
    def test_no_skip_when_filter_returns_true(self, mock_get_filter):
        """Test not skipping when filter condition evaluates to True."""
        mock_filter_service = MagicMock()
        mock_filter_service.filter_item.return_value = True
        mock_get_filter.return_value = mock_filter_service
        agent_config = {'where_clause': {'clause': 'should_keep_cluster == false', 'behavior': 'skip'}}
        context = {'should_keep_cluster': False}
        result = _should_skip_where_clause(agent_config, context)
        assert result is False
        mock_filter_service.filter_item.assert_called_once_with(context, 'should_keep_cluster == false')

    def test_no_skip_when_no_where_clause(self):
        """Test not skipping when no where clause is present."""
        agent_config = {}
        context = {'data': 'test'}
        result = _should_skip_where_clause(agent_config, context)
        assert result is False

    def test_no_skip_when_behavior_is_not_skip(self):
        """Test not skipping when where clause behavior is not 'skip'."""
        agent_config = {'where_clause': {'clause': 'status == "active"', 'behavior': 'filter'}}
        context = {'status': 'inactive'}
        result = _should_skip_where_clause(agent_config, context)
        assert result is False

    @patch('agent_actions.response_processing.where_parser.get_global_filter')
    def test_error_handling_with_passthrough_on_error_true(self, mock_get_filter):
        """Test error handling when passthrough_on_error is True (default)."""
        mock_get_filter.side_effect = Exception('Filter service error')
        agent_config = {'where_clause': {'clause': 'invalid_clause', 'behavior': 'skip', 'passthrough_on_error': True}}
        context = {'data': 'test'}
        result = _should_skip_where_clause(agent_config, context)
        assert result is True

    @patch('agent_actions.response_processing.where_parser.get_global_filter')
    def test_error_handling_with_passthrough_on_error_false(self, mock_get_filter):
        """Test error handling when passthrough_on_error is False."""
        mock_get_filter.side_effect = Exception('Filter service error')
        agent_config = {'where_clause': {'clause': 'invalid_clause', 'behavior': 'skip', 'passthrough_on_error': False}}
        context = {'data': 'test'}
        result = _should_skip_where_clause(agent_config, context)
        assert result is False

    @patch('agent_actions.response_processing.where_parser.get_global_filter')
    def test_error_handling_default_passthrough_on_error(self, mock_get_filter):
        """Test error handling with default passthrough_on_error setting."""
        mock_get_filter.side_effect = Exception('Filter service error')
        agent_config = {'where_clause': {'clause': 'invalid_clause', 'behavior': 'skip'}}
        context = {'data': 'test'}
        result = _should_skip_where_clause(agent_config, context)
        assert result is True

class TestRunDynamicAgent:
    """Test the run_dynamic_agent function integration."""

    @patch('agent_actions.llm_invocation.realtime.agent_builder')
    @patch('agent_actions.core.utils.processor_helpers.apply_drops')
    def test_executes_agent_when_no_guards(self, mock_apply_remove, mock_agent_builder):
        """Test normal agent execution when no guard conditions are present."""
        mock_apply_remove.return_value = {'processed': 'context'}
        mock_agent_builder.create_dynamic_agent.return_value = {'result': 'success'}
        agent_config = {'agent_type': 'test_agent'}
        context = {'data': 'test'}
        result, executed = run_dynamic_agent(agent_config, 'test_agent', context, 'test prompt')
        assert executed is True
        assert result == {'result': 'success'}
        mock_agent_builder.create_dynamic_agent.assert_called_once()

    @patch('agent_actions.core.utils.processor_helpers._should_skip_legacy_conditional')
    def test_skips_agent_when_legacy_conditional_returns_true(self, mock_should_skip):
        """Test agent skipping when legacy conditional indicates skip."""
        mock_should_skip.return_value = True
        agent_config = {'conditional_clause': 'validators.should_process'}
        context = {'data': 'test'}
        result, executed = run_dynamic_agent(agent_config, 'test_agent', context, 'test prompt')
        assert executed is False
        assert result == context
        mock_should_skip.assert_called_once_with(agent_config, context)

    @patch('agent_actions.core.utils.processor_helpers._should_skip_where_clause')
    @patch('agent_actions.core.utils.processor_helpers._should_skip_legacy_conditional')
    def test_skips_agent_when_where_clause_returns_true(self, mock_legacy_skip, mock_where_skip):
        """Test agent skipping when where clause indicates skip."""
        mock_legacy_skip.return_value = False
        mock_where_skip.return_value = True
        agent_config = {'where_clause': {'clause': 'should_keep_cluster == false', 'behavior': 'skip'}}
        context = {'should_keep_cluster': True}
        result, executed = run_dynamic_agent(agent_config, 'test_agent', context, 'test prompt')
        assert executed is False
        assert result == context
        mock_where_skip.assert_called_once_with(agent_config, context)

    @patch('agent_actions.llm_invocation.realtime.agent_builder')
    @patch('agent_actions.core.utils.processor_helpers.apply_drops')
    @patch('agent_actions.core.utils.processor_helpers._should_skip_where_clause')
    @patch('agent_actions.core.utils.processor_helpers._should_skip_legacy_conditional')
    def test_executes_agent_when_all_guards_pass(self, mock_legacy_skip, mock_where_skip, mock_apply_remove, mock_agent_builder):
        """Test agent execution when all guard conditions pass."""
        mock_legacy_skip.return_value = False
        mock_where_skip.return_value = False
        mock_apply_remove.return_value = {'processed': 'context'}
        mock_agent_builder.create_dynamic_agent.return_value = {'result': 'success'}
        agent_config = {'conditional_clause': 'validators.should_process', 'where_clause': {'clause': 'should_keep_cluster == false', 'behavior': 'skip'}}
        context = {'should_keep_cluster': False}
        result, executed = run_dynamic_agent(agent_config, 'test_agent', context, 'test prompt')
        assert executed is True
        assert result == {'result': 'success'}
        mock_legacy_skip.assert_called_once_with(agent_config, context)
        mock_where_skip.assert_called_once_with(agent_config, context)
        mock_agent_builder.create_dynamic_agent.assert_called_once()

    @patch('agent_actions.llm_invocation.realtime.agent_builder')
    @patch('agent_actions.core.utils.processor_helpers.apply_drops')
    def test_passes_all_parameters_to_agent_builder(self, mock_apply_remove, mock_agent_builder):
        """Test that all parameters are correctly passed to agent builder."""
        mock_apply_remove.return_value = {'processed': 'context'}
        mock_agent_builder.create_dynamic_agent.return_value = {'result': 'success'}
        agent_config = {'agent_type': 'test_agent'}
        context = {'data': 'test'}
        formatted_prompt = 'test prompt'
        tools_path = '/path/to/tools'
        tool_args = {'arg1': 'value1'}
        source_content = {'source': 'content'}
        result, executed = run_dynamic_agent(agent_config, 'test_agent', context, formatted_prompt, tools_path=tools_path, tool_args=tool_args, source_content=source_content)
        assert executed is True
        mock_agent_builder.create_dynamic_agent.assert_called_once_with(agent_config, 'test_agent', {'processed': 'context'}, formatted_prompt, tools_path=tools_path, tool_args=tool_args, source_content=source_content)

class TestToolAgentGuardIntegration:
    """Integration tests for tool agent guard behavior - the original issue scenario."""

    @patch('agent_actions.response_processing.where_parser.get_global_filter')
    @patch('agent_actions.llm_invocation.realtime.agent_builder')
    @patch('agent_actions.core.utils.processor_helpers.apply_drops')
    def test_tool_agent_with_skip_guard_condition_false(self, mock_apply_remove, mock_agent_builder, mock_get_filter):
        """Test tool agent execution when skip guard condition is False (should execute)."""
        mock_filter_service = MagicMock()
        mock_filter_service.filter_item.return_value = True
        mock_get_filter.return_value = mock_filter_service
        mock_apply_remove.return_value = {'should_keep_cluster': False}
        mock_agent_builder.create_dynamic_agent.return_value = [{'new_cluster': 'result'}]
        agent_config = {'model_vendor': 'tool', 'agent_type': 'create_new_clusters', 'where_clause': {'clause': 'should_keep_cluster == false', 'behavior': 'skip'}}
        context = {'should_keep_cluster': False}
        result, executed = run_dynamic_agent(agent_config, 'create_new_clusters', context, 'test prompt')
        assert executed is True
        assert result == [{'new_cluster': 'result'}]
        mock_filter_service.filter_item.assert_called_once_with(context, 'should_keep_cluster == false')
        mock_agent_builder.create_dynamic_agent.assert_called_once()

    @patch('agent_actions.response_processing.where_parser.get_global_filter')
    def test_tool_agent_with_skip_guard_condition_true(self, mock_get_filter):
        """Test tool agent skip when skip guard condition is True (should skip)."""
        mock_filter_service = MagicMock()
        mock_filter_service.filter_item.return_value = False
        mock_get_filter.return_value = mock_filter_service
        agent_config = {'model_vendor': 'tool', 'agent_type': 'create_new_clusters', 'where_clause': {'clause': 'should_keep_cluster == false', 'behavior': 'skip'}}
        context = {'should_keep_cluster': True}
        result, executed = run_dynamic_agent(agent_config, 'create_new_clusters', context, 'test prompt')
        assert executed is False
        assert result == context
        mock_filter_service.filter_item.assert_called_once_with(context, 'should_keep_cluster == false')

    @patch('agent_actions.response_processing.where_parser.get_global_filter')
    def test_tool_agent_guard_error_handling(self, mock_get_filter):
        """Test tool agent error handling in guard evaluation."""
        mock_get_filter.side_effect = Exception('Filter service error')
        agent_config = {'model_vendor': 'tool', 'agent_type': 'create_new_clusters', 'where_clause': {'clause': 'invalid_clause', 'behavior': 'skip', 'passthrough_on_error': True}}
        context = {'data': 'test'}
        result, executed = run_dynamic_agent(agent_config, 'create_new_clusters', context, 'test prompt')
        assert executed is False
        assert result == context
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
"""Tests for ActionExpander loop mode handling (sequential vs parallel)."""
import pytest
from agent_actions.response_processing.action_expander import ActionExpander

class TestActionExpanderLoopModes:
    """Test suite for loop execution modes."""

    def test_parallel_loop_dependencies(self):
        """Test that parallel mode creates independent iterations."""
        config = {'name': 'test_workflow', 'description': 'Test workflow', 'version': '1.0.0', 'defaults': {'model_vendor': 'openai', 'model_name': 'gpt-4o-mini'}, 'actions': [{'name': 'input', 'intent': 'Load input data', 'api_key': 'OPENAI_API_KEY'}, {'name': 'process', 'intent': 'Process data in parallel', 'api_key': 'OPENAI_API_KEY', 'loop': {'param': 'stage', 'range': [1, 3], 'mode': 'parallel'}}], 'plan': ['input', 'process <- input']}
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result['test_workflow']
        process_agents = [a for a in agents if a['agent_type'].startswith('process_')]
        assert len(process_agents) == 3
        for agent in process_agents:
            assert agent['dependencies'] == ['input']
            assert agent['loop_mode'] == 'parallel'

    def test_sequential_loop_dependencies(self):
        """Test that sequential mode creates dependency chain."""
        config = {'name': 'test_workflow', 'description': 'Test workflow', 'version': '1.0.0', 'defaults': {'model_vendor': 'openai', 'model_name': 'gpt-4o-mini'}, 'actions': [{'name': 'input', 'intent': 'Load input data', 'api_key': 'OPENAI_API_KEY'}, {'name': 'refine', 'intent': 'Refine data sequentially', 'api_key': 'OPENAI_API_KEY', 'loop': {'param': 'stage', 'range': [1, 4], 'mode': 'sequential'}}], 'plan': ['input', 'refine <- input']}
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result['test_workflow']
        refine_agents = [a for a in agents if a['agent_type'].startswith('refine_')]
        assert len(refine_agents) == 4
        assert refine_agents[0]['dependencies'] == ['input']
        assert refine_agents[1]['dependencies'] == ['refine_1']
        assert refine_agents[2]['dependencies'] == ['refine_2']
        assert refine_agents[3]['dependencies'] == ['refine_3']
        for agent in refine_agents:
            assert agent['loop_mode'] == 'sequential'

    def test_default_loop_mode_is_parallel(self):
        """Test that loops without explicit mode default to parallel."""
        config = {'name': 'test_workflow', 'description': 'Test workflow', 'version': '1.0.0', 'defaults': {'model_vendor': 'openai', 'model_name': 'gpt-4o-mini'}, 'actions': [{'name': 'input', 'intent': 'Load input data', 'api_key': 'OPENAI_API_KEY'}, {'name': 'process', 'intent': 'Process data', 'api_key': 'OPENAI_API_KEY', 'loop': {'param': 'i', 'range': [1, 2]}}], 'plan': ['input', 'process <- input']}
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result['test_workflow']
        process_agents = [a for a in agents if a['agent_type'].startswith('process_')]
        for agent in process_agents:
            assert agent['dependencies'] == ['input']
            assert agent['loop_mode'] == 'parallel'

    def test_sequential_loop_with_multiple_parent_deps(self):
        """Test sequential loop where first iteration has multiple dependencies."""
        config = {'name': 'test_workflow', 'description': 'Test workflow', 'version': '1.0.0', 'defaults': {'model_vendor': 'openai', 'model_name': 'gpt-4o-mini'}, 'actions': [{'name': 'input_a', 'intent': 'Load input A', 'api_key': 'OPENAI_API_KEY'}, {'name': 'input_b', 'intent': 'Load input B', 'api_key': 'OPENAI_API_KEY'}, {'name': 'merge', 'intent': 'Merge sequentially', 'api_key': 'OPENAI_API_KEY', 'loop': {'param': 'stage', 'range': [1, 3], 'mode': 'sequential'}}], 'plan': ['input_a', 'input_b', 'merge <- input_a, input_b']}
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result['test_workflow']
        merge_agents = [a for a in agents if a['agent_type'].startswith('merge_')]
        assert set(merge_agents[0]['dependencies']) == {'input_a', 'input_b'}
        assert merge_agents[1]['dependencies'] == ['merge_1']
        assert merge_agents[2]['dependencies'] == ['merge_2']

    def test_sequential_loop_single_iteration(self):
        """Test sequential loop with only one iteration."""
        config = {'name': 'test_workflow', 'description': 'Test workflow', 'version': '1.0.0', 'defaults': {'model_vendor': 'openai', 'model_name': 'gpt-4o-mini'}, 'actions': [{'name': 'input', 'intent': 'Load input', 'api_key': 'OPENAI_API_KEY'}, {'name': 'process', 'intent': 'Process once', 'api_key': 'OPENAI_API_KEY', 'loop': {'param': 'i', 'range': [1, 1], 'mode': 'sequential'}}], 'plan': ['input', 'process <- input']}
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result['test_workflow']
        process_agents = [a for a in agents if a['agent_type'].startswith('process_')]
        assert len(process_agents) == 1
        assert process_agents[0]['dependencies'] == ['input']
        assert process_agents[0]['loop_mode'] == 'sequential'

    def test_mixed_parallel_and_sequential_loops(self):
        """Test workflow with both parallel and sequential loops."""
        config = {'name': 'test_workflow', 'description': 'Test workflow', 'version': '1.0.0', 'defaults': {'model_vendor': 'openai', 'model_name': 'gpt-4o-mini'}, 'actions': [{'name': 'input', 'intent': 'Load input', 'api_key': 'OPENAI_API_KEY'}, {'name': 'parallel_process', 'intent': 'Process in parallel', 'api_key': 'OPENAI_API_KEY', 'loop': {'param': 'i', 'range': [1, 2], 'mode': 'parallel'}}, {'name': 'sequential_refine', 'intent': 'Refine sequentially', 'api_key': 'OPENAI_API_KEY', 'loop': {'param': 'stage', 'range': [1, 3], 'mode': 'sequential'}}], 'plan': ['input', 'parallel_process <- input', 'sequential_refine <- parallel_process']}
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result['test_workflow']
        parallel_agents = [a for a in agents if a['agent_type'].startswith('parallel_process_')]
        sequential_agents = [a for a in agents if a['agent_type'].startswith('sequential_refine_')]
        for agent in parallel_agents:
            assert agent['dependencies'] == ['input']
            assert agent['loop_mode'] == 'parallel'
        assert set(sequential_agents[0]['dependencies']) == {'parallel_process_1', 'parallel_process_2'}
        assert sequential_agents[1]['dependencies'] == ['sequential_refine_1']
        assert sequential_agents[2]['dependencies'] == ['sequential_refine_2']
        for agent in sequential_agents:
            assert agent['loop_mode'] == 'sequential'

    def test_loop_metadata_includes_mode(self):
        """Test that loop metadata includes execution mode."""
        config = {'name': 'test_workflow', 'description': 'Test workflow', 'version': '1.0.0', 'defaults': {'model_vendor': 'openai', 'model_name': 'gpt-4o-mini'}, 'actions': [{'name': 'process', 'intent': 'Process data', 'api_key': 'OPENAI_API_KEY', 'loop': {'param': 'i', 'range': [1, 2], 'mode': 'sequential'}}], 'plan': ['process']}
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result['test_workflow']
        for agent in agents:
            assert agent['is_loop_agent'] is True
            assert agent['loop_base_name'] == 'process'
            assert 'loop_iteration' in agent
            assert agent['loop_mode'] == 'sequential'
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
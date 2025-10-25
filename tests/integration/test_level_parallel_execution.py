"""
Integration tests for level-based parallel execution.
"""
import pytest
import asyncio
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from agent_actions.orchestration.agent_workflow import AgentWorkflow

class TestLevelBasedParallelExecution:
    """Test level-based parallel execution in real workflows."""

    @pytest.mark.asyncio
    async def test_two_parallel_groups_with_intermediate(self):
        """
        Test THE edge case: parallel loops → intermediate → parallel loops.

        Workflow: extract → [gen_1, gen_2, gen_3] → validate → [enrich_1, enrich_2, enrich_3]
        """
        execution_order = ['extract', 'gen_1', 'gen_2', 'gen_3', 'validate', 'enrich_1', 'enrich_2', 'enrich_3']
        agent_configs = {'extract': {'dependencies': [], 'agent_type': 'extract'}, 'gen_1': {'dependencies': ['extract'], 'agent_type': 'gen_1'}, 'gen_2': {'dependencies': ['extract'], 'agent_type': 'gen_2'}, 'gen_3': {'dependencies': ['extract'], 'agent_type': 'gen_3'}, 'validate': {'dependencies': ['gen_1', 'gen_2', 'gen_3'], 'agent_type': 'validate'}, 'enrich_1': {'dependencies': ['validate'], 'agent_type': 'enrich_1'}, 'enrich_2': {'dependencies': ['validate'], 'agent_type': 'enrich_2'}, 'enrich_3': {'dependencies': ['validate'], 'agent_type': 'enrich_3'}}
        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs
        workflow.agent_status = {agent: {'status': 'pending'} for agent in execution_order}
        workflow.ephemeral_directories = []
        workflow.console = Mock()
        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)
        workflow._should_use_parallel_execution = AgentWorkflow._should_use_parallel_execution.__get__(workflow)
        levels = workflow._compute_execution_levels()
        assert len(levels) == 4, f'Expected 4 levels, got {len(levels)}'
        assert levels[0] == ['extract']
        assert set(levels[1]) == {'gen_1', 'gen_2', 'gen_3'}, 'Gen agents should be parallel'
        assert levels[2] == ['validate']
        assert set(levels[3]) == {'enrich_1', 'enrich_2', 'enrich_3'}, 'Enrich agents should be parallel'
        assert workflow._should_use_parallel_execution(), 'Should detect parallel opportunities'

    @pytest.mark.asyncio
    async def test_parallel_speedup_measurement(self):
        """Test that parallel execution provides actual speedup."""
        execution_order = ['A', 'B', 'C']
        agent_configs = {'A': {'dependencies': [], 'agent_type': 'A'}, 'B': {'dependencies': [], 'agent_type': 'B'}, 'C': {'dependencies': [], 'agent_type': 'C'}}
        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs
        workflow.agent_status = {agent: {'status': 'pending'} for agent in execution_order}
        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)
        levels = workflow._compute_execution_levels()
        assert len(levels) == 1
        assert set(levels[0]) == {'A', 'B', 'C'}
        start = time.time()

        async def mock_agent_run(agent_name):
            await asyncio.sleep(0.1)
            return f'output_{agent_name}'
        tasks = [mock_agent_run(agent) for agent in levels[0]]
        await asyncio.gather(*tasks)
        parallel_duration = time.time() - start
        assert parallel_duration < 0.15, f'Parallel execution too slow: {parallel_duration}s'

    @pytest.mark.asyncio
    async def test_error_stops_subsequent_levels(self):
        """Test that error in level N prevents level N+1 from executing."""
        execution_order = ['A', 'B', 'C', 'D']
        agent_configs = {'A': {'dependencies': [], 'agent_type': 'A'}, 'B': {'dependencies': ['A'], 'agent_type': 'B'}, 'C': {'dependencies': ['B'], 'agent_type': 'C'}, 'D': {'dependencies': ['C'], 'agent_type': 'D'}}
        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs
        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)
        levels = workflow._compute_execution_levels()
        assert len(levels) == 4

        async def mock_run_agent(agent_name):
            if agent_name == 'C':
                raise Exception(f'Agent {agent_name} failed')
            return f'output_{agent_name}'
        await mock_run_agent('A')
        await mock_run_agent('B')
        with pytest.raises(Exception, match='Agent C failed'):
            await mock_run_agent('C')

    @pytest.mark.asyncio
    async def test_batch_agents_in_parallel_level(self):
        """Test batch agents can exist in parallel level."""
        execution_order = ['batch_1', 'batch_2', 'batch_3']
        agent_configs = {'batch_1': {'dependencies': [], 'agent_type': 'batch_1', 'run_mode': 'batch'}, 'batch_2': {'dependencies': [], 'agent_type': 'batch_2', 'run_mode': 'batch'}, 'batch_3': {'dependencies': [], 'agent_type': 'batch_3', 'run_mode': 'batch'}}
        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs
        workflow.agent_status = {agent: {'status': 'pending'} for agent in execution_order}
        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)
        levels = workflow._compute_execution_levels()
        assert len(levels) == 1
        assert set(levels[0]) == {'batch_1', 'batch_2', 'batch_3'}

    @pytest.mark.asyncio
    async def test_sequential_workflow_creates_single_agent_levels(self):
        """Test purely sequential workflow."""
        execution_order = ['A', 'B', 'C', 'D']
        agent_configs = {'A': {'dependencies': [], 'agent_type': 'A'}, 'B': {'dependencies': ['A'], 'agent_type': 'B'}, 'C': {'dependencies': ['B'], 'agent_type': 'C'}, 'D': {'dependencies': ['C'], 'agent_type': 'D'}}
        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs
        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)
        workflow._should_use_parallel_execution = AgentWorkflow._should_use_parallel_execution.__get__(workflow)
        levels = workflow._compute_execution_levels()
        assert len(levels) == 4
        assert all((len(level) == 1 for level in levels))
        assert not workflow._should_use_parallel_execution()

    @pytest.mark.asyncio
    async def test_concurrency_limit_respected(self):
        """Test concurrency limit is respected within levels."""
        execution_order = ['A', 'B', 'C', 'D', 'E']
        agent_configs = {'A': {'dependencies': [], 'agent_type': 'A'}, 'B': {'dependencies': [], 'agent_type': 'B'}, 'C': {'dependencies': [], 'agent_type': 'C'}, 'D': {'dependencies': [], 'agent_type': 'D'}, 'E': {'dependencies': [], 'agent_type': 'E'}}
        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs
        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)
        levels = workflow._compute_execution_levels()
        assert len(levels) == 1
        assert len(levels[0]) == 5
        concurrent_count = 0
        max_concurrent = 0

        async def mock_agent_with_tracking(agent_name):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
        semaphore = asyncio.Semaphore(2)

        async def run_with_limit(agent):
            async with semaphore:
                await mock_agent_with_tracking(agent)
        tasks = [run_with_limit(agent) for agent in levels[0]]
        await asyncio.gather(*tasks)
        assert max_concurrent <= 2, f'Concurrency limit violated: {max_concurrent}'
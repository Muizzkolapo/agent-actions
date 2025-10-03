"""
Performance benchmarks for parallel execution.
"""
import pytest
import asyncio
import time
from unittest.mock import Mock
from agent_actions.core.graph.agent_workflow import AgentWorkflow


class TestParallelPerformance:
    """Performance benchmarks for level-based parallel execution."""

    @pytest.mark.asyncio
    async def test_multi_level_parallel_speedup(self):
        """
        Test multi-level workflow with parallel speedup.

        Workflow: A → [B, C, D] → E → [F, G]
        Each agent: 0.1s
        Sequential: 7 × 0.1s = 0.7s
        Parallel: 4 levels × 0.1s = 0.4s
        Expected speedup: ~1.75×
        """
        execution_order = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': ['A']},
            'C': {'dependencies': ['A']},
            'D': {'dependencies': ['A']},
            'E': {'dependencies': ['B', 'C', 'D']},
            'F': {'dependencies': ['E']},
            'G': {'dependencies': ['E']},
        }

        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs

        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)

        levels = workflow._compute_execution_levels()

        # Verify levels: [A], [B,C,D], [E], [F,G]
        assert len(levels) == 4

        # Simulate parallel execution
        async def mock_agent(agent_name):
            await asyncio.sleep(0.1)
            return agent_name

        start = time.time()

        for level in levels:
            tasks = [mock_agent(agent) for agent in level]
            await asyncio.gather(*tasks)

        parallel_time = time.time() - start

        # Should take ~0.4s (4 levels × 0.1s)
        assert 0.35 <= parallel_time <= 0.50, f"Expected ~0.4s, got {parallel_time}s"

        # Sequential would be 0.7s
        sequential_time = len(execution_order) * 0.1

        speedup = sequential_time / parallel_time
        assert speedup >= 1.5, f"Expected speedup >= 1.5×, got {speedup:.2f}×"

    @pytest.mark.asyncio
    async def test_no_overhead_for_sequential(self):
        """Test sequential workflows have minimal overhead."""
        # A → B → C (purely sequential)
        execution_order = ['A', 'B', 'C']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': ['A']},
            'C': {'dependencies': ['B']},
        }

        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs

        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)

        levels = workflow._compute_execution_levels()

        async def mock_agent(agent_name):
            await asyncio.sleep(0.1)
            return agent_name

        # Time parallel execution path
        start = time.time()
        for level in levels:
            for agent in level:
                await mock_agent(agent)
        parallel_path_time = time.time() - start

        # Time sequential simulation
        start = time.time()
        for agent in execution_order:
            await mock_agent(agent)
        sequential_time = time.time() - start

        # Both should take ~same time
        overhead = abs(parallel_path_time - sequential_time)
        assert overhead < 0.05, f"Too much overhead: {overhead}s"

    @pytest.mark.asyncio
    async def test_large_parallel_group_performance(self):
        """Test performance with large parallel group."""
        # 10 agents all in parallel
        execution_order = [f'agent_{i}' for i in range(10)]
        agent_configs = {
            agent: {'dependencies': []} for agent in execution_order
        }

        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs

        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)

        levels = workflow._compute_execution_levels()

        # All 10 in one level
        assert len(levels) == 1
        assert len(levels[0]) == 10

        async def mock_agent(agent_name):
            await asyncio.sleep(0.1)
            return agent_name

        # Run with concurrency limit
        start = time.time()
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent

        async def run_with_limit(agent):
            async with semaphore:
                return await mock_agent(agent)

        tasks = [run_with_limit(agent) for agent in levels[0]]
        await asyncio.gather(*tasks)

        parallel_time = time.time() - start

        # With limit=5: 10 agents / 5 concurrent = 2 batches × 0.1s = ~0.2s
        assert 0.15 <= parallel_time <= 0.30, f"Expected ~0.2s, got {parallel_time}s"

        # Without limit would be ~0.1s, sequential would be ~1.0s
        speedup_vs_sequential = (10 * 0.1) / parallel_time
        assert speedup_vs_sequential >= 3.0, f"Expected speedup >= 3×, got {speedup_vs_sequential:.2f}×"

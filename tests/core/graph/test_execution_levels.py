"""
Tests for execution level computation in AgentWorkflow.
"""
import pytest
from agent_actions.core.graph.agent_workflow import AgentWorkflow
from agent_actions.core.exceptions import WorkflowError
from pathlib import Path
from unittest.mock import Mock, MagicMock


class TestExecutionLevels:
    """Test execution level computation from dependency graphs."""

    def create_mock_workflow(self, execution_order, agent_configs):
        """Helper to create a mock workflow with given execution order and configs."""
        workflow = Mock(spec=AgentWorkflow)
        workflow.execution_order = execution_order
        workflow.agent_configs = agent_configs

        # Bind the actual method to the mock
        workflow._compute_execution_levels = AgentWorkflow._compute_execution_levels.__get__(workflow)
        workflow._should_use_parallel_execution = AgentWorkflow._should_use_parallel_execution.__get__(workflow)

        return workflow

    def test_simple_linear_workflow(self):
        """Test linear workflow creates single-agent levels."""
        # A → B → C
        execution_order = ['A', 'B', 'C']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': ['A']},
            'C': {'dependencies': ['B']}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert levels == [['A'], ['B'], ['C']]
        assert not workflow._should_use_parallel_execution()

    def test_simple_parallel_fork(self):
        """Test fork pattern creates parallel level."""
        # A → [B, C, D]
        execution_order = ['A', 'B', 'C', 'D']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': ['A']},
            'C': {'dependencies': ['A']},
            'D': {'dependencies': ['A']}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert len(levels) == 2
        assert levels[0] == ['A']
        assert set(levels[1]) == {'B', 'C', 'D'}
        assert workflow._should_use_parallel_execution()

    def test_parallel_join(self):
        """Test join pattern waits for all parallel agents."""
        # [A, B, C] → D
        execution_order = ['A', 'B', 'C', 'D']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': []},
            'C': {'dependencies': []},
            'D': {'dependencies': ['A', 'B', 'C']}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert len(levels) == 2
        assert set(levels[0]) == {'A', 'B', 'C'}
        assert levels[1] == ['D']
        assert workflow._should_use_parallel_execution()

    def test_diamond_pattern(self):
        """Test diamond pattern with intermediate levels."""
        # A → [B, C] → D
        execution_order = ['A', 'B', 'C', 'D']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': ['A']},
            'C': {'dependencies': ['A']},
            'D': {'dependencies': ['B', 'C']}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert len(levels) == 3
        assert levels[0] == ['A']
        assert set(levels[1]) == {'B', 'C'}
        assert levels[2] == ['D']
        assert workflow._should_use_parallel_execution()

    def test_edge_case_intermediate_dependencies(self):
        """Test the edge case: parallel → sequential → parallel."""
        # A → [B, C, D] → E → [F, G, H]
        execution_order = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': ['A']},
            'C': {'dependencies': ['A']},
            'D': {'dependencies': ['A']},
            'E': {'dependencies': ['B', 'C', 'D']},
            'F': {'dependencies': ['E']},
            'G': {'dependencies': ['E']},
            'H': {'dependencies': ['E']}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert len(levels) == 4
        assert levels[0] == ['A']
        assert set(levels[1]) == {'B', 'C', 'D'}
        assert levels[2] == ['E']
        assert set(levels[3]) == {'F', 'G', 'H'}
        assert workflow._should_use_parallel_execution()

    def test_complex_multi_level(self):
        """Test complex workflow with multiple parallel levels."""
        # A → [B, C] → [D, E] → F
        execution_order = ['A', 'B', 'C', 'D', 'E', 'F']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': ['A']},
            'C': {'dependencies': ['A']},
            'D': {'dependencies': ['B', 'C']},
            'E': {'dependencies': ['B', 'C']},
            'F': {'dependencies': ['D', 'E']}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert len(levels) == 4
        assert levels[0] == ['A']
        assert set(levels[1]) == {'B', 'C'}
        assert set(levels[2]) == {'D', 'E'}
        assert levels[3] == ['F']
        assert workflow._should_use_parallel_execution()

    def test_no_dependencies_all_parallel(self):
        """Test agents with no dependencies are all level 0."""
        # [A, B, C] (all independent)
        execution_order = ['A', 'B', 'C']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': []},
            'C': {'dependencies': []}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert len(levels) == 1
        assert set(levels[0]) == {'A', 'B', 'C'}
        assert workflow._should_use_parallel_execution()

    def test_partial_dependencies(self):
        """Test mixed independent and dependent agents."""
        # A → B, C (independent) → D depends on C
        execution_order = ['A', 'B', 'C', 'D']
        agent_configs = {
            'A': {'dependencies': []},
            'B': {'dependencies': ['A']},
            'C': {'dependencies': []},
            'D': {'dependencies': ['C']}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        # A and C have no deps, so level 0
        # B depends on A, D depends on C, so level 1
        assert len(levels) == 2
        assert set(levels[0]) == {'A', 'C'}
        assert set(levels[1]) == {'B', 'D'}
        assert workflow._should_use_parallel_execution()

    def test_circular_dependency_detection(self):
        """Test circular dependencies are detected."""
        # A → B → C → A (circular)
        execution_order = ['A', 'B', 'C']
        agent_configs = {
            'A': {'dependencies': ['C']},  # Circular!
            'B': {'dependencies': ['A']},
            'C': {'dependencies': ['B']}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)

        with pytest.raises(WorkflowError) as exc_info:
            workflow._compute_execution_levels()

        assert 'circular_dependency' in str(exc_info.value)

    def test_empty_workflow(self):
        """Test empty workflow."""
        execution_order = []
        agent_configs = {}

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert levels == []
        assert not workflow._should_use_parallel_execution()

    def test_single_agent_workflow(self):
        """Test single agent workflow."""
        execution_order = ['A']
        agent_configs = {
            'A': {'dependencies': []}
        }

        workflow = self.create_mock_workflow(execution_order, agent_configs)
        levels = workflow._compute_execution_levels()

        assert levels == [['A']]
        assert not workflow._should_use_parallel_execution()  # Only 1 agent per level

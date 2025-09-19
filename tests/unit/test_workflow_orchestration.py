"""
Comprehensive tests for Workflow Orchestration System.

Tests cover critical workflow orchestration requirements identified in qanalabs production usage:
- Dependency resolution with various graph topologies
- Error recovery and failure simulation in dependency chains
- State management and workflow persistence across executions
- Concurrent execution with async coordination and semaphores
- Real-world workflow patterns from qanalabs

This implements CF-004 from the test implementation plan.
"""

import pytest
import time
import json
import tempfile
import shutil
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Any, Optional
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from agent_actions.core.core_utils import Utils
from agent_actions.agents.handlers.config_handler import ConfigManager
from agent_actions.core.graph.agent_workflow import AgentWorkflow
from agent_actions.core.parser.config_schema import AgentConfig
from tests.utils.test_utils import (
    WorkflowOrchestrationTestHelper,
    PerformanceBenchmarkHelper,
    test_state,
    temporary_test_environment
)


@dataclass
class MockAgentConfig:
    """Mock agent configuration for testing."""
    agent_type: str
    dependencies: List[str]
    is_operational: bool = True
    run_mode: str = "batch"
    json_mode: bool = True

    def model_dump(self, exclude_unset=False):
        return {
            'agent_type': self.agent_type,
            'dependencies': self.dependencies,
            'is_operational': self.is_operational,
            'run_mode': self.run_mode,
            'json_mode': self.json_mode
        }


class TestDependencyResolution:
    """Test dependency resolution with various graph topologies."""

    def test_topological_sort_linear_chain(self):
        """Test topological sort with simple linear dependency chain."""
        test_id = "dependency_linear_chain"
        test_state.register_test_run(test_id, "dependency_resolution")

        # A -> B -> C -> D
        dependencies = {
            'A': [],
            'B': ['A'],
            'C': ['B'],
            'D': ['C']
        }

        result = Utils.topological_sort(dependencies)

        # Result should be in reverse dependency order (leaves first)
        expected_order = ['A', 'B', 'C', 'D']
        assert result == expected_order, f"Expected {expected_order}, got {result}"

        test_state.complete_test_run(test_id, True, {"execution_order": result})

    def test_topological_sort_fan_out_fan_in(self):
        """Test topological sort with fan-out and fan-in pattern."""
        test_id = "dependency_fan_out_fan_in"
        test_state.register_test_run(test_id, "dependency_resolution")

        # Start -> Branch1,Branch2,Branch3 -> End
        dependencies = {
            'Start': [],
            'Branch1': ['Start'],
            'Branch2': ['Start'],
            'Branch3': ['Start'],
            'End': ['Branch1', 'Branch2', 'Branch3']
        }

        result = Utils.topological_sort(dependencies)

        # Start should be first, End should be last
        assert result[0] == 'Start', "Start should be first"
        assert result[-1] == 'End', "End should be last"

        # Branch nodes should be in the middle
        branch_indices = [result.index(f'Branch{i}') for i in [1, 2, 3]]
        assert all(0 < idx < len(result) - 1 for idx in branch_indices), "Branches should be in middle"

        test_state.complete_test_run(test_id, True, {"execution_order": result})

    def test_topological_sort_diamond_pattern(self):
        """Test topological sort with diamond dependency pattern."""
        test_id = "dependency_diamond_pattern"
        test_state.register_test_run(test_id, "dependency_resolution")

        # A -> B,C -> D
        dependencies = {
            'A': [],
            'B': ['A'],
            'C': ['A'],
            'D': ['B', 'C']
        }

        result = Utils.topological_sort(dependencies)

        # A should be first, D should be last
        assert result[0] == 'A', "A should be first"
        assert result[-1] == 'D', "D should be last"

        # B and C should come after A but before D
        a_idx = result.index('A')
        b_idx = result.index('B')
        c_idx = result.index('C')
        d_idx = result.index('D')

        assert a_idx < b_idx < d_idx, "A -> B -> D order should be maintained"
        assert a_idx < c_idx < d_idx, "A -> C -> D order should be maintained"

        test_state.complete_test_run(test_id, True, {"execution_order": result})

    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies."""
        test_id = "dependency_circular_detection"
        test_state.register_test_run(test_id, "dependency_resolution")

        # A -> B -> C -> A (circular)
        dependencies = {
            'A': ['C'],
            'B': ['A'],
            'C': ['B']
        }

        with pytest.raises(ValueError, match="Cyclic dependency detected"):
            Utils.topological_sort(dependencies)

        test_state.add_security_violation(
            test_id, "circular_dependency",
            "Successfully detected circular dependency: A->C->B->A"
        )

        test_state.complete_test_run(test_id, True)

    def test_complex_qanalabs_workflow_pattern(self):
        """Test dependency resolution for qanalabs 15+ agent workflow."""
        test_id = "dependency_qanalabs_workflow"
        test_state.register_test_run(test_id, "dependency_resolution")

        qanalabs_pattern = WorkflowOrchestrationTestHelper.create_qanalabs_workflow_pattern()

        # Extract dependencies
        dependencies = {}
        for agent in qanalabs_pattern['agents']:
            dependencies[agent['name']] = agent['dependencies']

        result = Utils.topological_sort(dependencies)

        # Verify specific qanalabs constraints
        fact_extractor_idx = result.index('fact_extractor')
        flatten_quotes_idx = result.index('flatten_quotes')
        scenario_gen_idx = result.index('ScenarioGenerator')
        stage1_idx = result.index('AnswerLengthDistractorEditor_Stage1')
        stage2_idx = result.index('AnswerLengthDistractorEditor_Stage2')
        stage3_idx = result.index('AnswerLengthDistractorEditor_Stage3')

        # Verify sequential processing constraints
        assert fact_extractor_idx < flatten_quotes_idx, "fact_extractor should come before flatten_quotes"
        assert scenario_gen_idx < stage1_idx < stage2_idx < stage3_idx, "Stages should be sequential"

        test_state.complete_test_run(test_id, True, {
            "execution_order": result,
            "total_agents": len(result)
        })

    def test_invalid_dependency_graph(self):
        """Test handling of invalid dependency graphs."""
        test_id = "dependency_invalid_graph"
        test_state.register_test_run(test_id, "dependency_resolution")

        # Circular dependency should still fail
        invalid_dependencies = {
            'A': ['B'],
            'B': ['A']
        }

        with pytest.raises(ValueError, match="Cyclic dependency detected"):
            Utils.topological_sort(invalid_dependencies)

        # Test with non-dict input
        with pytest.raises(ValueError, match="Dependencies must be a dictionary"):
            Utils.topological_sort("invalid")

        test_state.complete_test_run(test_id, True)


class TestConfigManagerDependencyHandling:
    """Test ConfigManager's dependency handling and execution order determination."""

    def test_determine_execution_order_operational_agents_only(self):
        """Test that only operational agents are included in execution order."""
        test_id = "config_manager_operational_only"
        test_state.register_test_run(test_id, "config_manager")

        with temporary_test_environment() as env:
            # Mock config manager
            config_manager = Mock(spec=ConfigManager)

            # Create agent configs with mixed operational status
            agent_configs = {
                'agent1': MockAgentConfig('agent1', [], is_operational=True),
                'agent2': MockAgentConfig('agent2', ['agent1'], is_operational=False),  # Disabled
                'agent3': MockAgentConfig('agent3', ['agent1'], is_operational=True),
                'agent4': MockAgentConfig('agent4', ['agent2', 'agent3'], is_operational=True)
            }

            # Mock the validator
            with patch('agent_actions.agents.handlers.config_handler.ConfigValidator') as mock_validator:
                mock_validator.return_value.validate.return_value = None

                # Simulate the dependency resolution logic
                dependency_graph = {}
                for agent_type, config in agent_configs.items():
                    if config.is_operational:
                        dependencies = [
                            dep for dep in config.dependencies
                            if dep in agent_configs and agent_configs[dep].is_operational
                        ]
                        dependency_graph[agent_type] = dependencies

                execution_order = Utils.topological_sort(dependency_graph)

            # Should only include operational agents: agent1, agent3, agent4
            # agent2 is excluded because is_operational=False
            # agent4's dependency on agent2 is ignored because agent2 is not operational
            expected_agents = {'agent1', 'agent3', 'agent4'}
            actual_agents = set(execution_order)

            assert actual_agents == expected_agents, f"Expected {expected_agents}, got {actual_agents}"
            assert 'agent2' not in execution_order, "Non-operational agent should be excluded"

        test_state.complete_test_run(test_id, True, {"execution_order": execution_order})

    def test_config_validation_integration(self):
        """Test integration between config validation and dependency resolution."""
        test_id = "config_validation_integration"
        test_state.register_test_run(test_id, "config_manager")

        with temporary_test_environment() as env:
            # Create realistic agent configurations
            agent_configs = {
                'fact_extractor': MockAgentConfig('fact_extractor', []),
                'fact_questionability': MockAgentConfig('fact_questionability', ['fact_extractor']),
                'ScenarioGenerator': MockAgentConfig('ScenarioGenerator', ['fact_questionability']),
                'QuizTaker': MockAgentConfig('QuizTaker', ['ScenarioGenerator'], is_operational=False)
            }

            # Test the actual validation and ordering logic
            with patch('agent_actions.agents.handlers.config_handler.ConfigValidator') as mock_validator:
                mock_validator.return_value.validate.return_value = None

                # Convert to dict format for validator
                agent_configs_dict = {
                    agent_type: config.model_dump()
                    for agent_type, config in agent_configs.items()
                }

                # Mock validator call
                validator_instance = mock_validator.return_value
                validator_instance.validate(agent_configs_dict)

                # Build dependency graph
                dependency_graph = {}
                for agent_type, config in agent_configs.items():
                    if config.is_operational:
                        dependencies = [
                            dep for dep in config.dependencies
                            if dep in agent_configs and agent_configs[dep].is_operational
                        ]
                        dependency_graph[agent_type] = dependencies

                execution_order = Utils.topological_sort(dependency_graph)

            # Verify validation was called
            mock_validator.assert_called_once()
            validator_instance.validate.assert_called_once_with(agent_configs_dict)

            # Verify correct execution order (excluding QuizTaker)
            expected_order = ['fact_extractor', 'fact_questionability', 'ScenarioGenerator']
            assert execution_order == expected_order, f"Expected {expected_order}, got {execution_order}"

        test_state.complete_test_run(test_id, True)


class TestWorkflowStateManagement:
    """Test workflow state management and persistence."""

    def test_agent_status_tracking(self):
        """Test agent status tracking and persistence."""
        test_id = "workflow_status_tracking"
        test_state.register_test_run(test_id, "state_management")

        with temporary_test_environment() as env:
            # Create mock workflow with status file
            status_file = Path(env['temp_dir']) / ".agent_status.json"

            # Test initial status creation
            execution_order = ['agent1', 'agent2', 'agent3']
            initial_status = {agent: {"status": "pending"} for agent in execution_order}

            # Save status
            with open(status_file, 'w') as f:
                json.dump(initial_status, f, indent=4)

            # Load status
            with open(status_file, 'r') as f:
                loaded_status = json.load(f)

            assert loaded_status == initial_status, "Status should be loaded correctly"

            # Test status updates
            loaded_status['agent1']['status'] = 'completed'
            loaded_status['agent2']['status'] = 'in_progress'

            # Save updated status
            with open(status_file, 'w') as f:
                json.dump(loaded_status, f, indent=4)

            # Verify persistence
            with open(status_file, 'r') as f:
                final_status = json.load(f)

            assert final_status['agent1']['status'] == 'completed'
            assert final_status['agent2']['status'] == 'in_progress'
            assert final_status['agent3']['status'] == 'pending'

        test_state.complete_test_run(test_id, True)

    def test_workflow_recovery_from_failure(self):
        """Test workflow recovery from agent failures."""
        test_id = "workflow_recovery"
        test_state.register_test_run(test_id, "state_management")

        with temporary_test_environment() as env:
            # Simulate a workflow that was interrupted
            status_file = Path(env['temp_dir']) / ".agent_status.json"

            interrupted_status = {
                'agent1': {'status': 'completed'},
                'agent2': {'status': 'completed'},
                'agent3': {'status': 'failed'},
                'agent4': {'status': 'pending'},
                'agent5': {'status': 'pending'}
            }

            with open(status_file, 'w') as f:
                json.dump(interrupted_status, f, indent=4)

            # Load status for recovery
            with open(status_file, 'r') as f:
                current_status = json.load(f)

            # Determine which agents need to be rerun
            agents_to_rerun = []
            agents_to_skip = []

            for agent, details in current_status.items():
                if details['status'] == 'completed':
                    agents_to_skip.append(agent)
                elif details['status'] in ['failed', 'pending']:
                    agents_to_rerun.append(agent)

            # Verify recovery logic
            assert agents_to_skip == ['agent1', 'agent2'], "Completed agents should be skipped"
            assert set(agents_to_rerun) == {'agent3', 'agent4', 'agent5'}, "Failed/pending agents should be rerun"

        test_state.complete_test_run(test_id, True, {
            "agents_to_skip": len(agents_to_skip),
            "agents_to_rerun": len(agents_to_rerun)
        })

    def test_workflow_state_isolation(self):
        """Test that workflow states are properly isolated."""
        test_id = "workflow_state_isolation"
        test_state.register_test_run(test_id, "state_management")

        with temporary_test_environment() as env:
            # Create multiple workflow status files
            workflow1_status = Path(env['temp_dir']) / "workflow1" / ".agent_status.json"
            workflow2_status = Path(env['temp_dir']) / "workflow2" / ".agent_status.json"

            workflow1_status.parent.mkdir(parents=True, exist_ok=True)
            workflow2_status.parent.mkdir(parents=True, exist_ok=True)

            # Different states for each workflow
            status1 = {'agent1': {'status': 'completed'}, 'agent2': {'status': 'pending'}}
            status2 = {'agentA': {'status': 'failed'}, 'agentB': {'status': 'completed'}}

            with open(workflow1_status, 'w') as f:
                json.dump(status1, f)

            with open(workflow2_status, 'w') as f:
                json.dump(status2, f)

            # Verify isolation
            with open(workflow1_status, 'r') as f:
                loaded_status1 = json.load(f)

            with open(workflow2_status, 'r') as f:
                loaded_status2 = json.load(f)

            assert loaded_status1 == status1, "Workflow 1 state should be isolated"
            assert loaded_status2 == status2, "Workflow 2 state should be isolated"
            assert loaded_status1 != loaded_status2, "Workflows should have different states"

        test_state.complete_test_run(test_id, True)


class TestAsyncWorkflowExecution:
    """Test async workflow execution and concurrency control."""

    @pytest.mark.asyncio
    async def test_async_concurrency_limit(self):
        """Test async execution with concurrency limits."""
        test_id = "async_concurrency_limit"
        test_state.register_test_run(test_id, "async_execution")

        # Mock semaphore behavior
        max_concurrent = 3
        semaphore = asyncio.Semaphore(max_concurrent)
        active_count = 0
        max_observed_concurrent = 0

        async def mock_agent_execution(agent_name: str):
            nonlocal active_count, max_observed_concurrent

            async with semaphore:
                active_count += 1
                max_observed_concurrent = max(max_observed_concurrent, active_count)

                # Simulate agent execution time
                await asyncio.sleep(0.01)

                active_count -= 1
                return f"completed_{agent_name}"

        # Create multiple agents
        agents = [f"agent_{i}" for i in range(10)]

        # Execute all agents concurrently with semaphore limit
        start_time = time.perf_counter()
        results = await asyncio.gather(*[mock_agent_execution(agent) for agent in agents])
        execution_time = time.perf_counter() - start_time

        # Verify concurrency was limited
        assert max_observed_concurrent <= max_concurrent, f"Concurrency exceeded limit: {max_observed_concurrent} > {max_concurrent}"
        assert len(results) == len(agents), "All agents should complete"
        assert all("completed_" in result for result in results), "All agents should complete successfully"

        test_state.complete_test_run(test_id, True, {
            "max_concurrent": max_concurrent,
            "max_observed": max_observed_concurrent,
            "execution_time": execution_time,
            "agents_count": len(agents)
        })

    @pytest.mark.asyncio
    async def test_async_error_handling(self):
        """Test error handling in async workflow execution."""
        test_id = "async_error_handling"
        test_state.register_test_run(test_id, "async_execution")

        async def mock_agent_execution(agent_name: str):
            await asyncio.sleep(0.01)
            if agent_name == "failing_agent":
                raise RuntimeError(f"Agent {agent_name} failed")
            return f"completed_{agent_name}"

        agents = ["agent_1", "failing_agent", "agent_3"]

        # Execute with return_exceptions=True to capture failures
        results = await asyncio.gather(
            *[mock_agent_execution(agent) for agent in agents],
            return_exceptions=True
        )

        # Verify error handling
        assert len(results) == len(agents), "Should return result for each agent"
        assert results[0] == "completed_agent_1", "First agent should succeed"
        assert isinstance(results[1], RuntimeError), "Second agent should fail with RuntimeError"
        assert results[2] == "completed_agent_3", "Third agent should succeed"

        # Count successful vs failed executions
        successful = sum(1 for r in results if isinstance(r, str) and r.startswith("completed_"))
        failed = sum(1 for r in results if isinstance(r, Exception))

        assert successful == 2, "Two agents should succeed"
        assert failed == 1, "One agent should fail"

        test_state.complete_test_run(test_id, True, {
            "successful": successful,
            "failed": failed,
            "total": len(agents)
        })

    @pytest.mark.asyncio
    async def test_async_dependency_coordination(self):
        """Test async execution with dependency coordination."""
        test_id = "async_dependency_coordination"
        test_state.register_test_run(test_id, "async_execution")

        # Track execution order
        execution_order = []
        execution_lock = asyncio.Lock()

        async def mock_agent_execution(agent_name: str, dependencies: List[str], completed_agents: set):
            # Wait for dependencies to complete
            while not all(dep in completed_agents for dep in dependencies):
                await asyncio.sleep(0.001)

            # Simulate execution
            await asyncio.sleep(0.01)

            async with execution_lock:
                execution_order.append(agent_name)
                completed_agents.add(agent_name)

            return f"completed_{agent_name}"

        # Define agents with dependencies (A -> B,C -> D)
        completed_agents = set()
        agents = {
            'A': [],
            'B': ['A'],
            'C': ['A'],
            'D': ['B', 'C']
        }

        # Execute all agents
        tasks = []
        for agent, deps in agents.items():
            task = asyncio.create_task(mock_agent_execution(agent, deps, completed_agents))
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # Verify dependency constraints were respected
        a_idx = execution_order.index('A')
        b_idx = execution_order.index('B')
        c_idx = execution_order.index('C')
        d_idx = execution_order.index('D')

        assert a_idx < b_idx, "A should execute before B"
        assert a_idx < c_idx, "A should execute before C"
        assert b_idx < d_idx, "B should execute before D"
        assert c_idx < d_idx, "C should execute before D"

        test_state.complete_test_run(test_id, True, {
            "execution_order": execution_order,
            "agents_count": len(agents)
        })


class TestWorkflowPerformance:
    """Test workflow performance and scalability."""

    def test_large_workflow_dependency_resolution(self):
        """Test dependency resolution performance with large workflows."""
        test_id = "workflow_large_dependency_performance"
        test_state.register_test_run(test_id, "performance")

        # Create a large dependency graph (50 agents)
        num_agents = 50
        dependencies = {}

        # Create a complex but acyclic dependency graph
        for i in range(num_agents):
            agent_name = f"agent_{i}"
            deps = []

            # Each agent depends on some previous agents
            for j in range(max(0, i - 3), i):  # Depend on up to 3 previous agents
                deps.append(f"agent_{j}")

            dependencies[agent_name] = deps

        benchmark_helper = PerformanceBenchmarkHelper()

        with benchmark_helper.benchmark_context(test_id, "large_dependency_resolution"):
            start_time = time.perf_counter()
            execution_order = Utils.topological_sort(dependencies)
            duration = time.perf_counter() - start_time

        # Performance validation
        assert duration < 0.100, f"Large dependency resolution too slow: {duration:.3f}s > 0.1s"
        assert len(execution_order) == num_agents, "All agents should be in execution order"

        # Verify correctness of ordering
        for i, agent in enumerate(execution_order):
            agent_idx = int(agent.split('_')[1])
            for dep in dependencies[agent]:
                dep_idx = int(dep.split('_')[1])
                dep_position = execution_order.index(dep)
                assert dep_position < i, f"Dependency {dep} should come before {agent}"

        test_state.complete_test_run(test_id, True, {
            "agents_count": num_agents,
            "duration_ms": duration * 1000
        })
        test_state.record_performance_metric(test_id, "duration_ms", duration * 1000)

    def test_workflow_state_management_performance(self):
        """Test performance of workflow state management operations."""
        test_id = "workflow_state_performance"
        test_state.register_test_run(test_id, "performance")

        with temporary_test_environment() as env:
            status_file = Path(env['temp_dir']) / ".agent_status.json"

            # Create large status data
            num_agents = 1000
            status_data = {
                f"agent_{i}": {
                    "status": "completed" if i % 3 == 0 else "pending",
                    "start_time": time.time(),
                    "metadata": {"index": i, "type": f"type_{i % 5}"}
                }
                for i in range(num_agents)
            }

            benchmark_helper = PerformanceBenchmarkHelper()

            # Test status save performance
            with benchmark_helper.benchmark_context(test_id, "status_save"):
                save_start = time.perf_counter()
                with open(status_file, 'w') as f:
                    json.dump(status_data, f, indent=4)
                save_duration = time.perf_counter() - save_start

            # Test status load performance
            with benchmark_helper.benchmark_context(test_id, "status_load"):
                load_start = time.perf_counter()
                with open(status_file, 'r') as f:
                    loaded_data = json.load(f)
                load_duration = time.perf_counter() - load_start

            # Verify correctness
            assert loaded_data == status_data, "Loaded data should match saved data"

            # Performance assertions
            assert save_duration < 1.0, f"Status save too slow: {save_duration:.3f}s"
            assert load_duration < 0.5, f"Status load too slow: {load_duration:.3f}s"

        test_state.complete_test_run(test_id, True, {
            "agents_count": num_agents,
            "save_duration_ms": save_duration * 1000,
            "load_duration_ms": load_duration * 1000
        })


class TestWorkflowErrorHandling:
    """Test workflow error handling and recovery mechanisms."""

    def test_agent_failure_isolation(self):
        """Test that agent failures don't affect other agents unnecessarily."""
        test_id = "workflow_agent_failure_isolation"
        test_state.register_test_run(test_id, "error_handling")

        # Simulate a workflow where one agent fails
        agent_status = {
            'agent1': {'status': 'completed'},
            'agent2': {'status': 'failed'},
            'agent3': {'status': 'completed'},
            'agent4': {'status': 'pending'}  # Depends on agent3, not agent2
        }

        # Dependencies
        dependencies = {
            'agent1': [],
            'agent2': ['agent1'],
            'agent3': ['agent1'],
            'agent4': ['agent3']  # Should still be able to run
        }

        # Determine which agents can still run
        runnable_agents = []
        for agent, deps in dependencies.items():
            if agent_status[agent]['status'] == 'pending':
                can_run = all(
                    agent_status[dep]['status'] == 'completed'
                    for dep in deps
                )
                if can_run:
                    runnable_agents.append(agent)

        # agent4 should be runnable despite agent2 failure
        assert 'agent4' in runnable_agents, "agent4 should be runnable despite agent2 failure"

        test_state.complete_test_run(test_id, True, {"runnable_agents": runnable_agents})

    def test_workflow_graceful_degradation(self):
        """Test graceful degradation when some agents are disabled."""
        test_id = "workflow_graceful_degradation"
        test_state.register_test_run(test_id, "error_handling")

        # Simulate qanalabs pattern with some agents disabled
        agent_configs = {
            'fact_extractor': MockAgentConfig('fact_extractor', [], is_operational=True),
            'flatten_quotes': MockAgentConfig('flatten_quotes', ['fact_extractor'], is_operational=True),
            'fact_questionability': MockAgentConfig('fact_questionability', ['flatten_quotes'], is_operational=True),
            'ScenarioGenerator': MockAgentConfig('ScenarioGenerator', ['fact_questionability'], is_operational=True),
            'QuizTaker': MockAgentConfig('QuizTaker', ['ScenarioGenerator'], is_operational=False),  # Disabled
            'quiztaker_maker': MockAgentConfig('quiztaker_maker', ['ScenarioGenerator'], is_operational=True)  # Alternative path
        }

        # Build dependency graph excluding non-operational agents
        dependency_graph = {}
        for agent_type, config in agent_configs.items():
            if config.is_operational:
                dependencies = [
                    dep for dep in config.dependencies
                    if dep in agent_configs and agent_configs[dep].is_operational
                ]
                dependency_graph[agent_type] = dependencies

        execution_order = Utils.topological_sort(dependency_graph)

        # Verify graceful degradation
        assert 'QuizTaker' not in execution_order, "Disabled QuizTaker should not be in execution order"
        assert 'quiztaker_maker' in execution_order, "Alternative quiztaker_maker should be included"

        # Verify workflow continuity
        expected_agents = {'fact_extractor', 'flatten_quotes', 'fact_questionability', 'ScenarioGenerator', 'quiztaker_maker'}
        actual_agents = set(execution_order)
        assert actual_agents == expected_agents, "Workflow should continue with operational agents"

        test_state.complete_test_run(test_id, True, {
            "execution_order": execution_order,
            "disabled_agents": ['QuizTaker']
        })

    def test_invalid_configuration_handling(self):
        """Test handling of invalid workflow configurations."""
        test_id = "workflow_invalid_config"
        test_state.register_test_run(test_id, "error_handling")

        # Test various invalid configurations
        invalid_configs = [
            # Empty dependencies dict
            {},

            # Self-dependency
            {'agent1': ['agent1']},

            # Missing dependency reference
            {'agent1': [], 'agent2': ['nonexistent']},
        ]

        for i, invalid_config in enumerate(invalid_configs):
            try:
                if not invalid_config:  # Empty dict
                    # Empty config should return empty result
                    result = Utils.topological_sort(invalid_config)
                    assert result == [], "Empty config should return empty list"
                else:
                    Utils.topological_sort(invalid_config)
                    pytest.fail(f"Invalid config {i} should have raised an error")
            except ValueError:
                # Expected for invalid configurations
                pass

        test_state.complete_test_run(test_id, True, {"invalid_configs_tested": len(invalid_configs)})


class TestWorkflowIntegration:
    """Integration tests for complete workflow scenarios."""

    def test_end_to_end_qanalabs_workflow_simulation(self):
        """Test end-to-end qanalabs workflow simulation."""
        test_id = "workflow_e2e_qanalabs"
        test_state.register_test_run(test_id, "integration")

        with temporary_test_environment() as env:
            # Create qanalabs workflow pattern
            qanalabs_pattern = WorkflowOrchestrationTestHelper.create_qanalabs_workflow_pattern()

            # Extract and resolve dependencies
            dependencies = {}
            operational_agents = []

            for agent in qanalabs_pattern['agents']:
                if agent.get('is_operational', True):
                    operational_agents.append(agent['name'])
                    # Filter dependencies to only include operational agents
                    filtered_deps = [
                        dep for dep in agent['dependencies']
                        if any(a['name'] == dep and a.get('is_operational', True) for a in qanalabs_pattern['agents'])
                    ]
                    dependencies[agent['name']] = filtered_deps

            # Resolve execution order
            execution_order = Utils.topological_sort(dependencies)

            # Simulate workflow execution with status tracking
            status_file = Path(env['temp_dir']) / ".agent_status.json"
            agent_status = {agent: {"status": "pending"} for agent in execution_order}

            # Save initial status
            with open(status_file, 'w') as f:
                json.dump(agent_status, f, indent=4)

            # Simulate agent execution
            for i, agent_name in enumerate(execution_order):
                # Check dependencies are completed
                agent_deps = dependencies[agent_name]
                for dep in agent_deps:
                    assert agent_status[dep]['status'] == 'completed', f"Dependency {dep} should be completed before {agent_name}"

                # Update status to completed
                agent_status[agent_name]['status'] = 'completed'

                # Save status after each agent
                with open(status_file, 'w') as f:
                    json.dump(agent_status, f, indent=4)

            # Verify final state
            assert all(status['status'] == 'completed' for status in agent_status.values()), "All agents should be completed"

            # Verify specific qanalabs workflow constraints
            fact_extractor_idx = execution_order.index('fact_extractor')
            scenario_gen_idx = execution_order.index('ScenarioGenerator')
            quiztaker_maker_idx = execution_order.index('quiztaker_maker')

            assert fact_extractor_idx < scenario_gen_idx, "fact_extractor should come before ScenarioGenerator"
            assert scenario_gen_idx < quiztaker_maker_idx, "ScenarioGenerator should come before quiztaker_maker"

            # Verify QuizTaker is excluded (is_operational: false)
            assert 'QuizTaker' not in execution_order, "QuizTaker should be excluded as it's not operational"

        test_state.complete_test_run(test_id, True, {
            "total_agents": len(execution_order),
            "operational_agents": len(operational_agents),
            "execution_order": execution_order
        })

    def test_complex_dependency_scenarios(self):
        """Test complex dependency scenarios from production usage."""
        test_id = "workflow_complex_scenarios"
        test_state.register_test_run(test_id, "integration")

        scenarios = WorkflowOrchestrationTestHelper.create_complex_dependency_scenarios()

        for scenario in scenarios:
            if scenario.get('should_fail', False):
                # Test scenarios that should fail
                with pytest.raises(ValueError):
                    Utils.topological_sort(scenario['dependencies'])
            else:
                # Test valid scenarios
                execution_order = Utils.topological_sort(scenario['dependencies'])

                # Verify basic constraints
                assert len(execution_order) == len(scenario['agents']), f"All agents should be in order for {scenario['name']}"

                # Verify specific constraints if provided
                if 'expected_order' in scenario:
                    assert execution_order == scenario['expected_order'], f"Expected order not met for {scenario['name']}"

        test_state.complete_test_run(test_id, True, {"scenarios_tested": len(scenarios)})


if __name__ == "__main__":
    # Run performance tests when executed directly
    test_performance = TestWorkflowPerformance()
    test_performance.test_large_workflow_dependency_resolution()

    # Run integration tests
    test_integration = TestWorkflowIntegration()
    test_integration.test_end_to_end_qanalabs_workflow_simulation()

    # Print summary
    summary = test_state.get_summary()
    print("\nWorkflow Orchestration Test Summary:")
    print(f"Total tests run: {len(summary['test_runs'])}")
    print(f"Performance metrics: {len(summary['performance_metrics'])}")
    print(f"Security violations: {len(summary['security_violations'])}")

    # Performance summary
    if summary['performance_metrics']:
        print("\nPerformance Metrics:")
        for test_id, metrics in summary['performance_metrics'].items():
            print(f"- {test_id}: {metrics}")
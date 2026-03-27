"""Tests for ActionLevelOrchestrator functionality."""

import pytest

from agent_actions.errors import WorkflowError
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator


class TestActionLevelOrchestrator:
    """Test suite for ActionLevelOrchestrator."""

    def test_simple_sequential_execution(self):
        """Test simple sequential execution order."""
        execution_order = ["agent_a", "agent_b", "agent_c"]
        agent_configs = {
            "agent_a": {"dependencies": []},
            "agent_b": {"dependencies": ["agent_a"]},
            "agent_c": {"dependencies": ["agent_b"]},
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        levels = orchestrator.compute_execution_levels()

        assert len(levels) == 3
        assert levels[0] == ["agent_a"]
        assert levels[1] == ["agent_b"]
        assert levels[2] == ["agent_c"]

    def test_parallel_execution_levels(self):
        """Test parallel execution when agents have no inter-dependencies."""
        execution_order = ["agent_a", "agent_b", "agent_c", "agent_d"]
        agent_configs = {
            "agent_a": {"dependencies": []},
            "agent_b": {"dependencies": []},
            "agent_c": {"dependencies": ["agent_a", "agent_b"]},
            "agent_d": {"dependencies": ["agent_c"]},
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        levels = orchestrator.compute_execution_levels()

        assert len(levels) == 3
        # First level: agents with no dependencies
        assert set(levels[0]) == {"agent_a", "agent_b"}
        # Second level: depends on first level
        assert levels[1] == ["agent_c"]
        # Third level: depends on second level
        assert levels[2] == ["agent_d"]

    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies."""
        execution_order = ["agent_a", "agent_b"]
        agent_configs = {
            "agent_a": {"dependencies": ["agent_b"]},
            "agent_b": {"dependencies": ["agent_a"]},
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)

        with pytest.raises(WorkflowError) as exc_info:
            orchestrator.compute_execution_levels()

        assert "Circular dependency detected" in str(exc_info.value)


class TestLoopDependencyExpansion:
    """Test suite for loop dependency expansion in ActionLevelOrchestrator."""

    def test_build_version_base_name_map(self):
        """Test building the loop base name mapping."""
        execution_order = [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
            "flatten_questions",
        ]
        agent_configs = {
            "extract_raw_qa_1": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 1,
            },
            "extract_raw_qa_2": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 2,
            },
            "extract_raw_qa_3": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 3,
            },
            "flatten_questions": {
                "dependencies": ["extract_raw_qa"],
            },
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        version_base_map = orchestrator._build_version_base_name_map()

        assert "extract_raw_qa" in version_base_map
        assert set(version_base_map["extract_raw_qa"]) == {
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
        }

    def test_expand_version_dependencies(self):
        """Test expanding loop base name dependencies."""
        execution_order = ["loop_1", "loop_2", "consumer"]
        agent_configs = {
            "loop_1": {"is_versioned_agent": True, "version_base_name": "loop"},
            "loop_2": {"is_versioned_agent": True, "version_base_name": "loop"},
            "consumer": {"dependencies": []},
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        version_base_map = {"loop": ["loop_1", "loop_2"]}

        # Test expansion of loop base name
        expanded = orchestrator._expand_version_dependencies(["loop"], version_base_map)
        assert set(expanded) == {"loop_1", "loop_2"}

        # Test mixed dependencies
        expanded = orchestrator._expand_version_dependencies(
            ["other_agent", "loop"], version_base_map
        )
        assert set(expanded) == {"other_agent", "loop_1", "loop_2"}

        # Test non-loop dependencies unchanged
        expanded = orchestrator._expand_version_dependencies(["regular_dep"], version_base_map)
        assert expanded == ["regular_dep"]

    def test_loop_dependency_execution_levels(self):
        """Test that loop dependencies are correctly expanded in execution levels."""
        execution_order = [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
            "flatten_questions",
        ]
        agent_configs = {
            "extract_raw_qa_1": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 1,
            },
            "extract_raw_qa_2": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 2,
            },
            "extract_raw_qa_3": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 3,
            },
            "flatten_questions": {
                "dependencies": ["extract_raw_qa"],  # References the base name
            },
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        levels = orchestrator.compute_execution_levels()

        # Should have 2 levels:
        # Level 0: All loop agents (no dependencies, can run in parallel)
        # Level 1: flatten_questions (depends on all loop agents)
        assert len(levels) == 2
        assert set(levels[0]) == {
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
        }
        assert levels[1] == ["flatten_questions"]

    def test_loop_dependency_without_expansion_would_fail(self):
        """Test that without expansion, the dependency check would fail."""
        # This test documents the bug that was fixed
        execution_order = [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "flatten_questions",
        ]
        agent_configs = {
            "extract_raw_qa_1": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
            },
            "extract_raw_qa_2": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
            },
            "flatten_questions": {
                "dependencies": ["extract_raw_qa"],  # Base name, not expanded
            },
        }

        # With the fix, this should work
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        levels = orchestrator.compute_execution_levels()

        assert len(levels) == 2
        assert set(levels[0]) == {"extract_raw_qa_1", "extract_raw_qa_2"}
        assert levels[1] == ["flatten_questions"]

    def test_multiple_loop_groups_dependency(self):
        """Test dependencies on multiple different loop groups."""
        execution_order = [
            "loop_a_1",
            "loop_a_2",
            "loop_b_1",
            "loop_b_2",
            "consumer",
        ]
        agent_configs = {
            "loop_a_1": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "loop_a",
            },
            "loop_a_2": {
                "dependencies": [],
                "is_versioned_agent": True,
                "version_base_name": "loop_a",
            },
            "loop_b_1": {
                "dependencies": ["loop_a"],  # Depends on loop_a
                "is_versioned_agent": True,
                "version_base_name": "loop_b",
            },
            "loop_b_2": {
                "dependencies": ["loop_a"],  # Depends on loop_a
                "is_versioned_agent": True,
                "version_base_name": "loop_b",
            },
            "consumer": {
                "dependencies": ["loop_a", "loop_b"],  # Depends on both
            },
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        levels = orchestrator.compute_execution_levels()

        # Level 0: loop_a_1, loop_a_2 (no deps)
        # Level 1: loop_b_1, loop_b_2 (depend on loop_a)
        # Level 2: consumer (depends on both loop_a and loop_b)
        assert len(levels) == 3
        assert set(levels[0]) == {"loop_a_1", "loop_a_2"}
        assert set(levels[1]) == {"loop_b_1", "loop_b_2"}
        assert levels[2] == ["consumer"]

    def test_mixed_loop_and_regular_dependencies(self):
        """Test dependencies that mix loop base names and regular agent names."""
        execution_order = [
            "setup",
            "loop_1",
            "loop_2",
            "consumer",
        ]
        agent_configs = {
            "setup": {
                "dependencies": [],
            },
            "loop_1": {
                "dependencies": ["setup"],
                "is_versioned_agent": True,
                "version_base_name": "loop",
            },
            "loop_2": {
                "dependencies": ["setup"],
                "is_versioned_agent": True,
                "version_base_name": "loop",
            },
            "consumer": {
                "dependencies": ["setup", "loop"],  # Mixed: regular + loop base
            },
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        levels = orchestrator.compute_execution_levels()

        # Level 0: setup
        # Level 1: loop_1, loop_2 (both depend on setup)
        # Level 2: consumer (depends on setup and all loop agents)
        assert len(levels) == 3
        assert levels[0] == ["setup"]
        assert set(levels[1]) == {"loop_1", "loop_2"}
        assert levels[2] == ["consumer"]


class TestShouldUseParallelExecution:
    """Test suite for parallel execution detection."""

    def test_sequential_workflow(self):
        """Test detection of sequential workflow."""
        execution_order = ["a", "b", "c"]
        agent_configs = {
            "a": {"dependencies": []},
            "b": {"dependencies": ["a"]},
            "c": {"dependencies": ["b"]},
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        assert not orchestrator.should_use_parallel_execution()

    def test_parallel_workflow(self):
        """Test detection of parallel workflow."""
        execution_order = ["a", "b", "c"]
        agent_configs = {
            "a": {"dependencies": []},
            "b": {"dependencies": []},
            "c": {"dependencies": ["a", "b"]},
        }
        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        assert orchestrator.should_use_parallel_execution()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

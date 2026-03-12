"""
Tests for WorkspaceIndex functionality.

Tests the workspace scanning, dependency graph building, and downstream
workflow discovery.
"""

import tempfile
from pathlib import Path

import pytest

from agent_actions.workflow.workspace_index import WorkspaceIndex


class TestWorkspaceIndex:
    """Test suite for WorkspaceIndex."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace with workflow configs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            # Create workflow A (no dependencies)
            workflow_a = workspace / "workflow_a" / "agent_config"
            workflow_a.mkdir(parents=True)
            (workflow_a / "workflow_a.yml").write_text("""
name: workflow_a
actions:
  - name: action_1
    intent: Do something
""")

            # Create workflow B (depends on A)
            workflow_b = workspace / "workflow_b" / "agent_config"
            workflow_b.mkdir(parents=True)
            (workflow_b / "workflow_b.yml").write_text("""
name: workflow_b
actions:
  - name: action_1
    intent: Do something
    dependencies:
      - workflow: workflow_a
""")

            # Create workflow C (depends on A)
            workflow_c = workspace / "workflow_c" / "agent_config"
            workflow_c.mkdir(parents=True)
            (workflow_c / "workflow_c.yml").write_text("""
name: workflow_c
actions:
  - name: action_1
    intent: Do something
    dependencies:
      - workflow: workflow_a
""")

            # Create workflow D (depends on B and C)
            workflow_d = workspace / "workflow_d" / "agent_config"
            workflow_d.mkdir(parents=True)
            (workflow_d / "workflow_d.yml").write_text("""
name: workflow_d
actions:
  - name: action_1
    intent: Do something
    dependencies:
      - workflow: workflow_b
      - workflow: workflow_c
""")

            yield workspace

    @pytest.fixture
    def workspace_index(self, temp_workspace):
        """Create a WorkspaceIndex for the temp workspace."""
        index = WorkspaceIndex(temp_workspace)
        index.scan_workspace()
        return index

    def test_reverse_dependency_graph_built_correctly(self, workspace_index):
        """Test that reverse dependency graph is built correctly."""
        # workflow_a should have B and C as downstream
        assert workspace_index.reverse_dependency_graph["workflow_a"] == {
            "workflow_b",
            "workflow_c",
        }
        # workflow_b should have D as downstream
        assert workspace_index.reverse_dependency_graph["workflow_b"] == {"workflow_d"}
        # workflow_c should have D as downstream
        assert workspace_index.reverse_dependency_graph["workflow_c"] == {"workflow_d"}
        # workflow_d has no downstream
        assert workspace_index.reverse_dependency_graph.get("workflow_d", set()) == set()

    def test_topological_sort_downstream(self, workspace_index):
        """Test topological sorting of downstream workflows."""
        # From A: B and C can run in any order, but D must come after both
        sorted_downstream = workspace_index.topological_sort_downstream("workflow_a")

        # All three downstream workflows should be included
        assert len(sorted_downstream) == 3
        assert set(sorted_downstream) == {"workflow_b", "workflow_c", "workflow_d"}

        # D must be last
        assert sorted_downstream[-1] == "workflow_d"
        # B and C must come before D
        assert sorted_downstream.index("workflow_b") < sorted_downstream.index("workflow_d")
        assert sorted_downstream.index("workflow_c") < sorted_downstream.index("workflow_d")

    def test_topological_sort_single_downstream(self, workspace_index):
        """Test topological sort with single downstream workflow."""
        sorted_downstream = workspace_index.topological_sort_downstream("workflow_b")
        assert sorted_downstream == ["workflow_d"]

    def test_topological_sort_no_downstream(self, workspace_index):
        """Test topological sort when no downstream exists."""
        sorted_downstream = workspace_index.topological_sort_downstream("workflow_d")
        assert sorted_downstream == []

    def test_empty_workspace(self):
        """Test handling of empty workspace."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            index = WorkspaceIndex(workspace)
            index.scan_workspace()

            assert len(index.dependency_graph) == 0
            assert index.topological_sort_downstream("nonexistent") == []

    def test_nonexistent_workspace(self):
        """Test handling of non-existent workspace."""
        index = WorkspaceIndex(Path("/nonexistent/path"))
        index.scan_workspace()

        assert len(index.dependency_graph) == 0


class TestWorkspaceIndexCycleDetection:
    """Test cycle detection in downstream dependencies."""

    @pytest.fixture
    def cyclic_workspace(self):
        """Create a workspace with cyclic dependencies."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            # Create workflow A (depends on C - creates cycle)
            workflow_a = workspace / "workflow_a" / "agent_config"
            workflow_a.mkdir(parents=True)
            (workflow_a / "workflow_a.yml").write_text("""
name: workflow_a
actions:
  - name: action_1
    dependencies:
      - workflow: workflow_c
""")

            # Create workflow B (depends on A)
            workflow_b = workspace / "workflow_b" / "agent_config"
            workflow_b.mkdir(parents=True)
            (workflow_b / "workflow_b.yml").write_text("""
name: workflow_b
actions:
  - name: action_1
    dependencies:
      - workflow: workflow_a
""")

            # Create workflow C (depends on B - completes cycle)
            workflow_c = workspace / "workflow_c" / "agent_config"
            workflow_c.mkdir(parents=True)
            (workflow_c / "workflow_c.yml").write_text("""
name: workflow_c
actions:
  - name: action_1
    dependencies:
      - workflow: workflow_b
""")

            yield workspace

    def test_cycle_detection_raises_error(self, cyclic_workspace):
        """Test that cyclic dependencies raise WorkflowError."""
        from agent_actions.errors import WorkflowError

        index = WorkspaceIndex(cyclic_workspace)
        index.scan_workspace()

        # Try to sort downstream from any node in the cycle
        with pytest.raises(WorkflowError) as exc_info:
            index.topological_sort_downstream("workflow_a")

        assert "Cyclic dependency" in str(exc_info.value)

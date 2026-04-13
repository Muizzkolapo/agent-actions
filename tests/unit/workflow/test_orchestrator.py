"""Tests for WorkflowOrchestrator.

Covers:
- Workflow DAG discovery from config directory
- Execution plan resolution (downstream, upstream, full)
- Cycle detection
- Missing workflow handling
- Upstream ref validation
"""

import pytest

from agent_actions.errors import ConfigurationError, WorkflowError
from agent_actions.workflow.orchestrator import WorkflowOrchestrator


def _write_workflow(config_dir, name, upstream=None):
    """Write a minimal workflow YAML to the config directory."""
    lines = [f"name: {name}", "description: test", "actions:"]
    lines.append(f"  - name: {name}_action")
    lines.append("    intent: do something")
    if upstream:
        lines.append("upstream:")
        for ref in upstream:
            lines.append(f"  - workflow: {ref['workflow']}")
            actions = ref.get("actions", [f"{ref['workflow']}_action"])
            lines.append(f"    actions: [{', '.join(actions)}]")
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / f"{name}.yml").write_text("\n".join(lines))


class TestWorkflowDAGDiscovery:
    """Test workflow graph discovery from config files."""

    def test_no_config_dir(self, tmp_path):
        orch = WorkflowOrchestrator(tmp_path)
        assert orch.graph == {}

    def test_single_workflow_no_upstream(self, tmp_path):
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "ingest")
        orch = WorkflowOrchestrator(tmp_path)
        assert "ingest" in orch.graph
        assert orch.graph["ingest"] == []

    def test_linear_chain(self, tmp_path):
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "ingest")
        _write_workflow(config_dir, "enrich", upstream=[{"workflow": "ingest"}])
        _write_workflow(config_dir, "analyze", upstream=[{"workflow": "enrich"}])

        orch = WorkflowOrchestrator(tmp_path)
        assert orch.graph["ingest"] == []
        assert orch.graph["enrich"] == ["ingest"]
        assert orch.graph["analyze"] == ["enrich"]

    def test_fan_in(self, tmp_path):
        """Multiple workflows feed into one."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "source_a")
        _write_workflow(config_dir, "source_b")
        _write_workflow(
            config_dir,
            "merge",
            upstream=[
                {"workflow": "source_a"},
                {"workflow": "source_b"},
            ],
        )

        orch = WorkflowOrchestrator(tmp_path)
        assert set(orch.graph["merge"]) == {"source_a", "source_b"}

    def test_fan_out(self, tmp_path):
        """One workflow feeds into multiple."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "ingest")
        _write_workflow(config_dir, "branch_a", upstream=[{"workflow": "ingest"}])
        _write_workflow(config_dir, "branch_b", upstream=[{"workflow": "ingest"}])

        orch = WorkflowOrchestrator(tmp_path)
        assert set(orch.reverse_graph["ingest"]) == {"branch_a", "branch_b"}

    def test_reverse_graph(self, tmp_path):
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "ingest")
        _write_workflow(config_dir, "enrich", upstream=[{"workflow": "ingest"}])

        orch = WorkflowOrchestrator(tmp_path)
        assert orch.reverse_graph["ingest"] == ["enrich"]
        assert orch.reverse_graph["enrich"] == []

    def test_non_yaml_files_ignored(self, tmp_path):
        config_dir = tmp_path / "agent_config"
        config_dir.mkdir(parents=True)
        (config_dir / "readme.md").write_text("# Not a workflow")
        _write_workflow(config_dir, "valid")

        orch = WorkflowOrchestrator(tmp_path)
        assert "valid" in orch.graph
        assert len(orch.graph) == 1

    def test_per_workflow_layout(self, tmp_path):
        """Discovers configs from agent_workflow/*/agent_config/ layout."""
        wf_root = tmp_path / "agent_workflow"
        _write_workflow(wf_root / "ingest" / "agent_config", "ingest")
        _write_workflow(
            wf_root / "enrich" / "agent_config",
            "enrich",
            upstream=[{"workflow": "ingest"}],
        )

        orch = WorkflowOrchestrator(tmp_path)
        assert "ingest" in orch.graph
        assert "enrich" in orch.graph
        assert orch.graph["enrich"] == ["ingest"]


class TestExecutionPlanResolution:
    """Test resolve_execution_plan for various directions."""

    def _setup_chain(self, tmp_path):
        """Create a linear chain: ingest -> enrich -> analyze."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "ingest")
        _write_workflow(config_dir, "enrich", upstream=[{"workflow": "ingest"}])
        _write_workflow(config_dir, "analyze", upstream=[{"workflow": "enrich"}])
        return WorkflowOrchestrator(tmp_path)

    def test_downstream_from_root(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        plan = orch.resolve_execution_plan("ingest", "downstream")
        assert plan == ["ingest", "enrich", "analyze"]

    def test_downstream_from_middle(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        plan = orch.resolve_execution_plan("enrich", "downstream")
        assert plan == ["enrich", "analyze"]

    def test_downstream_from_leaf(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        plan = orch.resolve_execution_plan("analyze", "downstream")
        assert plan == ["analyze"]

    def test_upstream_from_leaf(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        plan = orch.resolve_execution_plan("analyze", "upstream")
        assert plan == ["ingest", "enrich", "analyze"]

    def test_upstream_from_middle(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        plan = orch.resolve_execution_plan("enrich", "upstream")
        assert plan == ["ingest", "enrich"]

    def test_upstream_from_root(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        plan = orch.resolve_execution_plan("ingest", "upstream")
        assert plan == ["ingest"]

    def test_full_lineage(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        plan = orch.resolve_execution_plan("enrich", "full")
        assert plan == ["ingest", "enrich", "analyze"]

    def test_missing_workflow_raises(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        with pytest.raises(ConfigurationError, match="not found"):
            orch.resolve_execution_plan("nonexistent", "downstream")

    def test_diamond_dependency(self, tmp_path):
        """Diamond: A -> B, A -> C, B -> D, C -> D."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "a")
        _write_workflow(config_dir, "b", upstream=[{"workflow": "a"}])
        _write_workflow(config_dir, "c", upstream=[{"workflow": "a"}])
        _write_workflow(
            config_dir,
            "d",
            upstream=[{"workflow": "b"}, {"workflow": "c"}],
        )

        orch = WorkflowOrchestrator(tmp_path)
        plan = orch.resolve_execution_plan("a", "downstream")
        # a must come before b and c, b and c must come before d
        assert plan[0] == "a"
        assert plan[-1] == "d"
        assert set(plan) == {"a", "b", "c", "d"}

    def test_circular_dependency_raises(self, tmp_path):
        """Cycle: a -> b -> c -> a."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "a", upstream=[{"workflow": "c"}])
        _write_workflow(config_dir, "b", upstream=[{"workflow": "a"}])
        _write_workflow(config_dir, "c", upstream=[{"workflow": "b"}])

        orch = WorkflowOrchestrator(tmp_path)
        with pytest.raises(WorkflowError, match="Circular dependency"):
            orch.resolve_execution_plan("a", "downstream")

    def test_invalid_direction_raises(self, tmp_path):
        orch = self._setup_chain(tmp_path)
        with pytest.raises(ValueError, match="Invalid direction"):
            orch.resolve_execution_plan("ingest", "sideways")


class TestUpstreamRefValidation:
    """Test validate_upstream_refs."""

    def test_valid_refs(self, tmp_path):
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "ingest")

        orch = WorkflowOrchestrator(tmp_path)
        # Should not raise
        orch.validate_upstream_refs(
            "enrich",
            [{"workflow": "ingest", "actions": ["ingest_action"]}],
        )

    def test_missing_upstream_workflow_raises(self, tmp_path):
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "enrich")

        orch = WorkflowOrchestrator(tmp_path)
        with pytest.raises(ConfigurationError, match="not found"):
            orch.validate_upstream_refs(
                "enrich",
                [{"workflow": "nonexistent", "actions": ["some_action"]}],
            )

    def test_missing_upstream_action_raises(self, tmp_path):
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "ingest")

        orch = WorkflowOrchestrator(tmp_path)
        with pytest.raises(ConfigurationError, match="not found in upstream"):
            orch.validate_upstream_refs(
                "enrich",
                [{"workflow": "ingest", "actions": ["nonexistent_action"]}],
            )

    def test_no_config_dir_raises(self, tmp_path):
        orch = WorkflowOrchestrator(tmp_path)
        with pytest.raises(ConfigurationError, match="not found"):
            orch.validate_upstream_refs(
                "enrich",
                [{"workflow": "ingest", "actions": ["extract"]}],
            )

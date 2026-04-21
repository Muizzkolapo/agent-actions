"""Integration test: --downstream scopes virtual actions to triggering upstream.

Reproduces the exact bug from the bug report: two upstreams feed one
downstream, --downstream from one upstream should only resolve that
upstream's data — not stale data from the other.
"""

from agent_actions.workflow.config_pipeline import _inject_upstream_virtual_actions
from agent_actions.workflow.orchestrator import WorkflowOrchestrator
from tests.conftest import make_mock_config_manager as _make_manager
from tests.conftest import write_workflow_config as _write_workflow


class TestDownstreamScopeEndToEnd:
    """Full pipeline: orchestrator builds plan → scope map → filtered virtual actions."""

    def test_fan_in_downstream_from_one_upstream(self, tmp_path):
        """Bug repro: qanalabs_quiz_gen and code_centered_quiz both feed
        run_thinkific_gen. Running --downstream from code_centered_quiz
        should only resolve code_centered_quiz's actions."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "qanalabs_quiz_gen")
        _write_workflow(config_dir, "code_centered_quiz")
        _write_workflow(
            config_dir,
            "run_thinkific_gen",
            upstream=[
                {"workflow": "qanalabs_quiz_gen", "actions": ["format_quiz_text"]},
                {"workflow": "code_centered_quiz", "actions": ["format_code_blocks"]},
            ],
        )

        # Step 1: Orchestrator resolves execution plan
        orch = WorkflowOrchestrator(tmp_path)
        plan = orch.resolve_execution_plan("code_centered_quiz", "downstream")
        assert "code_centered_quiz" in plan
        assert "run_thinkific_gen" in plan
        assert "qanalabs_quiz_gen" not in plan  # not in chain

        # Step 2: Build scope map
        scope_map = orch.build_upstream_scope_map(plan)
        thinkific_scope = scope_map["run_thinkific_gen"]
        assert thinkific_scope == ["code_centered_quiz"]

        # Step 3: Inject virtual actions with scope
        manager = _make_manager(
            [
                {"workflow": "qanalabs_quiz_gen", "actions": ["format_quiz_text"]},
                {"workflow": "code_centered_quiz", "actions": ["format_code_blocks"]},
            ],
            agent_name="run_thinkific_gen",
        )
        virtual_actions = _inject_upstream_virtual_actions(manager, upstream_scope=thinkific_scope)

        # Only code_centered_quiz's action should be present
        assert "format_code_blocks" in virtual_actions
        assert "format_quiz_text" not in virtual_actions
        assert virtual_actions["format_code_blocks"].source_workflow == "code_centered_quiz"

    def test_fan_in_downstream_from_other_upstream(self, tmp_path):
        """Same setup, but triggered from qanalabs_quiz_gen instead."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "qanalabs_quiz_gen")
        _write_workflow(config_dir, "code_centered_quiz")
        _write_workflow(
            config_dir,
            "run_thinkific_gen",
            upstream=[
                {"workflow": "qanalabs_quiz_gen", "actions": ["format_quiz_text"]},
                {"workflow": "code_centered_quiz", "actions": ["format_code_blocks"]},
            ],
        )

        orch = WorkflowOrchestrator(tmp_path)
        plan = orch.resolve_execution_plan("qanalabs_quiz_gen", "downstream")
        scope_map = orch.build_upstream_scope_map(plan)

        manager = _make_manager(
            [
                {"workflow": "qanalabs_quiz_gen", "actions": ["format_quiz_text"]},
                {"workflow": "code_centered_quiz", "actions": ["format_code_blocks"]},
            ],
            agent_name="run_thinkific_gen",
        )
        virtual_actions = _inject_upstream_virtual_actions(
            manager, upstream_scope=scope_map["run_thinkific_gen"]
        )

        assert "format_quiz_text" in virtual_actions
        assert "format_code_blocks" not in virtual_actions

    def test_standalone_run_resolves_all_upstreams(self, tmp_path):
        """Without --downstream, all upstreams are resolved (existing behavior)."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "qanalabs_quiz_gen")
        _write_workflow(config_dir, "code_centered_quiz")
        _write_workflow(
            config_dir,
            "run_thinkific_gen",
            upstream=[
                {"workflow": "qanalabs_quiz_gen", "actions": ["format_quiz_text"]},
                {"workflow": "code_centered_quiz", "actions": ["format_code_blocks"]},
            ],
        )

        manager = _make_manager(
            [
                {"workflow": "qanalabs_quiz_gen", "actions": ["format_quiz_text"]},
                {"workflow": "code_centered_quiz", "actions": ["format_code_blocks"]},
            ],
            agent_name="run_thinkific_gen",
        )
        # upstream_scope=None — standalone run
        virtual_actions = _inject_upstream_virtual_actions(manager, upstream_scope=None)

        assert "format_quiz_text" in virtual_actions
        assert "format_code_blocks" in virtual_actions

    def test_diamond_downstream_preserves_both_paths(self, tmp_path):
        """Diamond: A -> B, A -> C, B -> D, C -> D.
        Running --downstream from A includes all four — D gets both B and C."""
        config_dir = tmp_path / "agent_config"
        _write_workflow(config_dir, "a")
        _write_workflow(config_dir, "b", upstream=[{"workflow": "a", "actions": ["a_action"]}])
        _write_workflow(config_dir, "c", upstream=[{"workflow": "a", "actions": ["a_action"]}])
        _write_workflow(
            config_dir,
            "d",
            upstream=[
                {"workflow": "b", "actions": ["b_action"]},
                {"workflow": "c", "actions": ["c_action"]},
            ],
        )

        orch = WorkflowOrchestrator(tmp_path)
        plan = orch.resolve_execution_plan("a", "downstream")
        scope_map = orch.build_upstream_scope_map(plan)

        manager = _make_manager(
            [
                {"workflow": "b", "actions": ["b_action"]},
                {"workflow": "c", "actions": ["c_action"]},
            ],
            agent_name="d",
        )
        virtual_actions = _inject_upstream_virtual_actions(manager, upstream_scope=scope_map["d"])

        # Both paths are in the plan — D should get both
        assert "b_action" in virtual_actions
        assert "c_action" in virtual_actions

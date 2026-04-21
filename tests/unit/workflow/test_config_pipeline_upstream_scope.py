"""Tests for upstream_scope filtering in _inject_upstream_virtual_actions.

Verifies that when upstream_scope is set (by --downstream chain), only
virtual actions from in-scope upstreams are injected.
"""

from agent_actions.workflow.config_pipeline import _inject_upstream_virtual_actions
from tests.conftest import make_mock_config_manager as _make_manager


class TestUpstreamScopeFiltering:
    """_inject_upstream_virtual_actions respects upstream_scope."""

    def test_none_scope_keeps_all_upstreams(self):
        """upstream_scope=None (standalone run) injects all declared upstreams."""
        manager = _make_manager(
            [
                {"workflow": "wf_a", "actions": ["extract"]},
                {"workflow": "wf_b", "actions": ["classify"]},
            ]
        )

        result = _inject_upstream_virtual_actions(manager, upstream_scope=None)
        assert set(result.keys()) == {"extract", "classify"}
        assert result["extract"].source_workflow == "wf_a"
        assert result["classify"].source_workflow == "wf_b"

    def test_scope_filters_to_single_upstream(self):
        """upstream_scope=['wf_a'] keeps only wf_a's actions."""
        manager = _make_manager(
            [
                {"workflow": "wf_a", "actions": ["extract"]},
                {"workflow": "wf_b", "actions": ["classify"]},
            ]
        )

        result = _inject_upstream_virtual_actions(manager, upstream_scope=["wf_a"])
        assert set(result.keys()) == {"extract"}
        assert result["extract"].source_workflow == "wf_a"

    def test_scope_filters_to_other_upstream(self):
        """upstream_scope=['wf_b'] keeps only wf_b's actions."""
        manager = _make_manager(
            [
                {"workflow": "wf_a", "actions": ["extract"]},
                {"workflow": "wf_b", "actions": ["classify"]},
            ]
        )

        result = _inject_upstream_virtual_actions(manager, upstream_scope=["wf_b"])
        assert set(result.keys()) == {"classify"}

    def test_scope_with_both_upstreams(self):
        """upstream_scope=['wf_a', 'wf_b'] keeps all (diamond case)."""
        manager = _make_manager(
            [
                {"workflow": "wf_a", "actions": ["extract"]},
                {"workflow": "wf_b", "actions": ["classify"]},
            ]
        )

        result = _inject_upstream_virtual_actions(manager, upstream_scope=["wf_a", "wf_b"])
        assert set(result.keys()) == {"extract", "classify"}

    def test_empty_scope_returns_empty(self):
        """upstream_scope=[] (no upstreams in plan) returns no virtual actions."""
        manager = _make_manager(
            [
                {"workflow": "wf_a", "actions": ["extract"]},
            ]
        )

        result = _inject_upstream_virtual_actions(manager, upstream_scope=[])
        assert result == {}

    def test_single_upstream_unaffected(self):
        """Workflow with one upstream — scope containing it is a no-op."""
        manager = _make_manager(
            [
                {"workflow": "wf_a", "actions": ["extract", "transform"]},
            ]
        )

        result = _inject_upstream_virtual_actions(manager, upstream_scope=["wf_a"])
        assert set(result.keys()) == {"extract", "transform"}

    def test_scope_with_unknown_workflow_is_harmless(self):
        """upstream_scope referencing a workflow not in declarations is fine."""
        manager = _make_manager(
            [
                {"workflow": "wf_a", "actions": ["extract"]},
            ]
        )

        result = _inject_upstream_virtual_actions(manager, upstream_scope=["wf_x"])
        assert result == {}

    def test_no_upstream_config_returns_empty(self):
        """No upstream declarations — scope is irrelevant."""
        manager = _make_manager([])
        result = _inject_upstream_virtual_actions(manager, upstream_scope=["wf_a"])
        assert result == {}

    def test_scope_preserves_multiple_actions_from_same_upstream(self):
        """Scoping to one upstream preserves all of its declared actions."""
        manager = _make_manager(
            [
                {"workflow": "wf_a", "actions": ["step1", "step2", "step3"]},
                {"workflow": "wf_b", "actions": ["other"]},
            ]
        )

        result = _inject_upstream_virtual_actions(manager, upstream_scope=["wf_a"])
        assert set(result.keys()) == {"step1", "step2", "step3"}
        assert all(v.source_workflow == "wf_a" for v in result.values())

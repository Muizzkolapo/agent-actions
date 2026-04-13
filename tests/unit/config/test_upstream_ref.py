"""Tests for UpstreamRef model and upstream field on WorkflowConfig.

Covers:
- UpstreamRef validation (missing workflow, empty actions, extra fields)
- WorkflowConfig collision detection (local vs upstream, cross-upstream)
- Backward compatibility (workflows without upstream parse correctly)
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import UpstreamRef, WorkflowConfig


class TestUpstreamRef:
    """UpstreamRef model validation."""

    def test_valid_upstream_ref(self):
        ref = UpstreamRef(workflow="ingest", actions=["extract", "classify"])
        assert ref.workflow == "ingest"
        assert ref.actions == ["extract", "classify"]

    def test_missing_workflow_raises(self):
        with pytest.raises(ValidationError, match="workflow"):
            UpstreamRef(actions=["extract"])

    def test_missing_actions_raises(self):
        with pytest.raises(ValidationError, match="actions"):
            UpstreamRef(workflow="ingest")

    def test_empty_actions_raises(self):
        with pytest.raises(ValidationError, match="at least 1"):
            UpstreamRef(workflow="ingest", actions=[])

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            UpstreamRef(workflow="ingest", actions=["extract"], unknown_field="bad")

    def test_single_action(self):
        ref = UpstreamRef(workflow="ingest", actions=["final_step"])
        assert ref.actions == ["final_step"]


def _make_workflow(
    name="test_workflow",
    actions=None,
    upstream=None,
):
    """Helper to create a WorkflowConfig with minimal boilerplate."""
    if actions is None:
        actions = [{"name": "action_a", "intent": "do something"}]
    return WorkflowConfig.model_validate(
        {
            "name": name,
            "description": "Test workflow",
            "actions": actions,
            "upstream": upstream,
        }
    )


class TestWorkflowConfigUpstream:
    """WorkflowConfig validation with upstream declarations."""

    def test_no_upstream_works(self):
        """Existing workflows without upstream still parse correctly."""
        wf = _make_workflow()
        assert wf.upstream is None

    def test_valid_upstream(self):
        wf = _make_workflow(
            upstream=[{"workflow": "ingest", "actions": ["extract"]}],
        )
        assert len(wf.upstream) == 1
        assert wf.upstream[0].workflow == "ingest"
        assert wf.upstream[0].actions == ["extract"]

    def test_multiple_upstream_workflows(self):
        wf = _make_workflow(
            upstream=[
                {"workflow": "ingest", "actions": ["extract"]},
                {"workflow": "reference", "actions": ["load_taxonomy"]},
            ],
        )
        assert len(wf.upstream) == 2

    def test_collision_local_vs_upstream_raises(self):
        """Action name collision between local and upstream."""
        with pytest.raises(ValidationError, match="Action name collision.*action_a"):
            _make_workflow(
                actions=[{"name": "action_a", "intent": "do something"}],
                upstream=[{"workflow": "ingest", "actions": ["action_a"]}],
            )

    def test_collision_across_upstreams_raises(self):
        """Same action imported from two different upstream workflows."""
        with pytest.raises(ValidationError, match="Action 'extract' imported from both"):
            _make_workflow(
                upstream=[
                    {"workflow": "ingest", "actions": ["extract"]},
                    {"workflow": "other", "actions": ["extract"]},
                ],
            )

    def test_no_collision_different_names(self):
        """Different action names across local and upstream — no error."""
        wf = _make_workflow(
            actions=[{"name": "local_action", "intent": "do something"}],
            upstream=[{"workflow": "ingest", "actions": ["extract"]}],
        )
        assert wf.upstream is not None

    def test_upstream_with_multiple_actions(self):
        wf = _make_workflow(
            upstream=[{"workflow": "ingest", "actions": ["extract", "classify", "final"]}],
        )
        assert len(wf.upstream[0].actions) == 3

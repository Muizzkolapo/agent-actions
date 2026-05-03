"""Tests for AgentWorkflow._prepare_action_configs — canonical injection point."""

from unittest.mock import MagicMock

from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.models import WorkflowRuntimeConfig


def _build_workflow_for_prepare(action_configs):
    """Build a minimal AgentWorkflow to test _prepare_action_configs."""
    wf = object.__new__(AgentWorkflow)
    metadata = MagicMock()
    metadata.action_configs = action_configs
    wf.metadata = metadata
    wf.workflow_session_id = "workflow_abc123"
    wf.config = MagicMock(spec=WorkflowRuntimeConfig)
    return wf


class TestPrepareActionConfigs:
    """_prepare_action_configs injects action_name and workflow_session_id."""

    def test_injects_action_name_for_all_actions(self):
        configs = {
            "extract_claims": {"kind": "llm"},
            "flatten_questions": {"kind": "tool"},
            "score_quality": {"kind": "llm"},
        }
        wf = _build_workflow_for_prepare(configs)

        wf._prepare_action_configs()

        assert configs["extract_claims"]["action_name"] == "extract_claims"
        assert configs["flatten_questions"]["action_name"] == "flatten_questions"
        assert configs["score_quality"]["action_name"] == "score_quality"

    def test_injects_workflow_session_id_for_all_actions(self):
        configs = {
            "action_a": {"kind": "llm"},
            "action_b": {"kind": "tool"},
        }
        wf = _build_workflow_for_prepare(configs)

        wf._prepare_action_configs()

        assert configs["action_a"]["workflow_session_id"] == "workflow_abc123"
        assert configs["action_b"]["workflow_session_id"] == "workflow_abc123"

    def test_action_name_matches_dict_key(self):
        """action_name must equal the dict key, not any 'name' field in the config."""
        configs = {
            "my_action": {"kind": "llm", "name": "Some Display Name"},
        }
        wf = _build_workflow_for_prepare(configs)

        wf._prepare_action_configs()

        assert configs["my_action"]["action_name"] == "my_action"

    def test_clears_version_correlation_registry(self):
        """_prepare_action_configs must clear stale correlation IDs from prior runs."""
        from agent_actions.utils.correlation import VersionIdGenerator

        # Seed the registry with a stale entry
        VersionIdGenerator._version_correlation_registry = {"stale": "value"}

        configs = {"action_a": {"kind": "llm"}}
        wf = _build_workflow_for_prepare(configs)

        wf._prepare_action_configs()

        assert VersionIdGenerator._version_correlation_registry == {}

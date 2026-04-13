"""Tests for error context enrichment ordering in AgentWorkflow.

Verifies that:
- Context is enriched BEFORE handle_workflow_error fires the event
- The isinstance guard handles non-dict .context
- Both async and sequential paths enrich correctly
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.models import (
    CoreServices,
    SupportServices,
    WorkflowRuntimeConfig,
    WorkflowServices,
    WorkflowState,
)


def _build_workflow(execution_order=None):
    """Build an AgentWorkflow instance bypassing __init__."""
    wf = object.__new__(AgentWorkflow)

    execution_order = execution_order or ["agent_a"]
    agent_configs = {name: {"agent_type": name, "type": "llm"} for name in execution_order}

    metadata = MagicMock()
    metadata.agent_name = "test_workflow"
    metadata.execution_order = execution_order
    metadata.action_indices = {name: idx for idx, name in enumerate(execution_order)}
    metadata.action_configs = agent_configs
    wf.metadata = metadata

    wf.config = MagicMock(spec=WorkflowRuntimeConfig)

    runtime = MagicMock()
    runtime.state = WorkflowState()
    runtime.console = MagicMock()
    wf.runtime = runtime

    core = MagicMock(spec=CoreServices)
    core.state_manager = MagicMock()
    core.action_executor = MagicMock()
    core.action_level_orchestrator = MagicMock()
    core.action_level_orchestrator.compute_execution_levels.return_value = [["agent_a"]]
    support = MagicMock(spec=SupportServices)
    support.manifest_manager = MagicMock()
    wf.services = WorkflowServices(core=core, support=support)

    wf.event_logger = MagicMock()

    return wf


class TestSequentialErrorEnrichment:
    """Verify enrichment ordering in _run_workflow_with_context (sequential)."""

    def test_context_set_before_handle_workflow_error(self):
        """The .context dict must be populated BEFORE the event logger fires."""
        wf = _build_workflow()
        error = RuntimeError("action kaboom")

        wf.services.core.action_executor.execute_action_sync.side_effect = error

        # Track the state of error.context when handle_workflow_error is called
        captured_context = {}

        def capture_context(exc, **kwargs):
            if hasattr(exc, "context") and isinstance(exc.context, dict):
                captured_context.update(exc.context)

        wf.event_logger.handle_workflow_error.side_effect = capture_context

        with patch("agent_actions.workflow.coordinator.get_manager") as mock_gm:
            mock_gm.return_value.context.return_value.__enter__ = MagicMock()
            mock_gm.return_value.context.return_value.__exit__ = MagicMock(return_value=False)
            wf.services.core.state_manager.is_completed.return_value = False

            with pytest.raises(RuntimeError):
                wf._run_workflow_with_context(datetime.now())

        # Context was available to handle_workflow_error
        assert captured_context["workflow"] == "test_workflow"
        assert captured_context["operation"] == "sequential_workflow_execution"

    def test_enrichment_on_exception_without_context(self):
        """Bare exception (no .context attr) gets a fresh dict."""
        wf = _build_workflow()
        error = ValueError("no context attr")

        wf.services.core.action_executor.execute_action_sync.side_effect = error

        with patch("agent_actions.workflow.coordinator.get_manager") as mock_gm:
            mock_gm.return_value.context.return_value.__enter__ = MagicMock()
            mock_gm.return_value.context.return_value.__exit__ = MagicMock(return_value=False)
            wf.services.core.state_manager.is_completed.return_value = False

            with pytest.raises(ValueError) as exc_info:
                wf._run_workflow_with_context(datetime.now())

        ctx = exc_info.value.context
        assert isinstance(ctx, dict)
        assert ctx["workflow"] == "test_workflow"

    def test_enrichment_preserves_existing_context(self):
        """Existing .context keys should not be lost."""
        wf = _build_workflow()
        error = RuntimeError("fail")
        error.context = {"action_name": "agent_a", "custom": "data"}

        wf.services.core.action_executor.execute_action_sync.side_effect = error

        with patch("agent_actions.workflow.coordinator.get_manager") as mock_gm:
            mock_gm.return_value.context.return_value.__enter__ = MagicMock()
            mock_gm.return_value.context.return_value.__exit__ = MagicMock(return_value=False)
            wf.services.core.state_manager.is_completed.return_value = False

            with pytest.raises(RuntimeError) as exc_info:
                wf._run_workflow_with_context(datetime.now())

        ctx = exc_info.value.context
        assert ctx["custom"] == "data"
        assert ctx["workflow"] == "test_workflow"

    def test_non_dict_context_replaced(self):
        """If .context is a string (not dict), it gets replaced safely."""
        wf = _build_workflow()
        error = RuntimeError("fail")
        error.context = "I am a string, not a dict"

        wf.services.core.action_executor.execute_action_sync.side_effect = error

        with patch("agent_actions.workflow.coordinator.get_manager") as mock_gm:
            mock_gm.return_value.context.return_value.__enter__ = MagicMock()
            mock_gm.return_value.context.return_value.__exit__ = MagicMock(return_value=False)
            wf.services.core.state_manager.is_completed.return_value = False

            with pytest.raises(RuntimeError) as exc_info:
                wf._run_workflow_with_context(datetime.now())

        ctx = exc_info.value.context
        assert isinstance(ctx, dict)
        assert ctx["workflow"] == "test_workflow"

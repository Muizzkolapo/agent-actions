"""Tests for AgentWorkflow.async_run execution path."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.models import (
    CoreServices,
    SupportServices,
    WorkflowRuntimeConfig,
    WorkflowServices,
    WorkflowState,
)

# ── Helpers ─────────────────────────────────────────────────────────────


def _build_workflow(execution_order=None, agent_configs=None, state=None):
    """Build an AgentWorkflow instance bypassing __init__.

    Uses object.__new__ to skip AgentWorkflow.__init__ which has 7+ side effects
    (config loading, storage init, dependency orchestration, etc.).  This lets us
    test async_run in isolation by injecting mock collaborators directly.
    """
    wf = object.__new__(AgentWorkflow)

    execution_order = execution_order or ["agent_a", "agent_b"]
    agent_configs = agent_configs or {
        name: {"agent_type": name, "type": "llm"} for name in execution_order
    }

    # Metadata (accessed via properties)
    metadata = MagicMock()
    metadata.agent_name = "test_workflow"
    metadata.execution_order = execution_order
    metadata.action_indices = {name: idx for idx, name in enumerate(execution_order)}
    metadata.action_configs = agent_configs
    wf.metadata = metadata

    # Config
    wf.config = MagicMock(spec=WorkflowRuntimeConfig)
    wf.config.run_upstream = False
    wf.config.run_downstream = False

    # Runtime state
    runtime = MagicMock()
    runtime.state = state or WorkflowState()
    runtime.console = MagicMock()
    wf.runtime = runtime

    # Services
    core = MagicMock(spec=CoreServices)
    core.state_manager = MagicMock()
    core.action_executor = MagicMock()
    core.action_level_orchestrator = MagicMock()
    support = MagicMock(spec=SupportServices)
    support.manifest_manager = MagicMock()
    wf.services = WorkflowServices(core=core, support=support)

    # Event logger
    wf.event_logger = MagicMock()

    # Dependency orchestrator (needed for _resolve_downstream_workflows)
    wf.dependency_orchestrator = MagicMock()

    # Storage backend
    wf.storage_backend = MagicMock()

    return wf


def _mock_manager():
    """Create a mock EventManager whose context() works as a context manager."""
    mgr = MagicMock()
    mgr.context.return_value.__enter__ = MagicMock()
    mgr.context.return_value.__exit__ = MagicMock(return_value=False)
    return mgr


# ── async_run: upstream resolution ─────────────────────────────────────


class TestAsyncRunUpstreamResolution:
    """Tests for the upstream dependency resolution phase of async_run."""

    @pytest.mark.asyncio
    async def test_returns_none_when_upstream_not_ready(self):
        """async_run should return None when upstream resolution returns False."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=False)

        result = await wf.async_run()

        assert result is None
        wf.event_logger.log_workflow_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_when_upstream_succeeds(self):
        """async_run should proceed past upstream check when it returns True."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)

        mgr = _mock_manager()
        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = []

        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = await wf.async_run()

        # With no levels, finalize should be called and result is success
        assert result == ("success", {})
        wf.event_logger.log_workflow_start.assert_called_once()


# ── async_run: level execution ─────────────────────────────────────────


class TestAsyncRunLevelExecution:
    """Tests for level-by-level execution in async_run."""

    @pytest.mark.asyncio
    async def test_executes_each_level(self):
        """async_run should call execute_level_async for each level."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)
        wf._resolve_downstream_workflows = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = [
            ["agent_a"],
            ["agent_b"],
        ]
        orchestrator.execute_level_async = AsyncMock(return_value=True)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = await wf.async_run()

        assert result == ("success", {})
        assert orchestrator.execute_level_async.call_count == 2

    @pytest.mark.asyncio
    async def test_level_execution_params_passed_correctly(self):
        """The LevelExecutionParams should include correct fields."""
        wf = _build_workflow(execution_order=["agent_a"])
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)
        wf._resolve_downstream_workflows = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = [["agent_a"]]
        orchestrator.execute_level_async = AsyncMock(return_value=True)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            await wf.async_run(concurrency_limit=10)

        call_args = orchestrator.execute_level_async.call_args[0][0]
        assert call_args.level_idx == 0
        assert call_args.level_actions == ["agent_a"]
        assert call_args.action_indices == {"agent_a": 0}
        assert call_args.concurrency_limit == 10

    @pytest.mark.asyncio
    async def test_stops_when_level_incomplete(self):
        """async_run should return early when a level returns False (incomplete)."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = [
            ["agent_a"],
            ["agent_b"],
        ]
        # First level incomplete
        orchestrator.execute_level_async = AsyncMock(return_value=False)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = await wf.async_run()

        # Should return None (early exit, no finalize)
        assert result is None
        assert orchestrator.execute_level_async.call_count == 1
        wf.event_logger.finalize_workflow.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_manager_context_for_known_actions(self):
        """async_run should call manager.set_context for actions in action_indices."""
        wf = _build_workflow(execution_order=["agent_a", "agent_b"])
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)
        wf._resolve_downstream_workflows = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = [["agent_a", "agent_b"]]
        orchestrator.execute_level_async = AsyncMock(return_value=True)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            await wf.async_run()

        # set_context should have been called for each action in the level
        context_calls = mgr.set_context.call_args_list
        action_names = [c.kwargs.get("action_name") for c in context_calls]
        assert "agent_a" in action_names
        assert "agent_b" in action_names

    @pytest.mark.asyncio
    async def test_concurrency_limit_default(self):
        """Default concurrency_limit should be 5."""
        wf = _build_workflow(execution_order=["agent_a"])
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)
        wf._resolve_downstream_workflows = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = [["agent_a"]]
        orchestrator.execute_level_async = AsyncMock(return_value=True)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            await wf.async_run()  # No explicit concurrency_limit

        call_args = orchestrator.execute_level_async.call_args[0][0]
        assert call_args.concurrency_limit == 5


# ── async_run: completion and downstream ───────────────────────────────


class TestAsyncRunCompletion:
    """Tests for workflow completion and downstream resolution in async_run."""

    @pytest.mark.asyncio
    async def test_success_returns_tuple(self):
        """Successful async_run should return ('success', {})."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)
        wf._resolve_downstream_workflows = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = [["agent_a"]]
        orchestrator.execute_level_async = AsyncMock(return_value=True)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = await wf.async_run()

        assert result == ("success", {})
        wf.event_logger.finalize_workflow.assert_called_once()

    @pytest.mark.asyncio
    async def test_downstream_failure_returns_none(self):
        """When downstream resolution fails, should return None."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)
        wf._resolve_downstream_workflows = MagicMock(return_value=False)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = [["agent_a"]]
        orchestrator.execute_level_async = AsyncMock(return_value=True)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = await wf.async_run()

        assert result is None
        wf._resolve_downstream_workflows.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_receives_elapsed_time(self):
        """finalize_workflow should receive a positive elapsed_time."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)
        wf._resolve_downstream_workflows = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = []

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            await wf.async_run()

        call_kwargs = wf.event_logger.finalize_workflow.call_args[1]
        assert "elapsed_time" in call_kwargs
        assert isinstance(call_kwargs["elapsed_time"], float)
        assert call_kwargs["elapsed_time"] >= 0

    @pytest.mark.asyncio
    async def test_workflow_start_logged_as_async(self):
        """log_workflow_start should be called with is_async=True."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)
        wf._resolve_downstream_workflows = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = []

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            await wf.async_run()

        call_args = wf.event_logger.log_workflow_start.call_args
        assert call_args[1]["is_async"] is True


# ── async_run: error handling ──────────────────────────────────────────


class TestAsyncRunErrorHandling:
    """Tests for exception handling in async_run."""

    @pytest.mark.asyncio
    async def test_exception_sets_state_failed(self):
        """An exception during level execution should set state.failed = True."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.side_effect = RuntimeError("boom")

        mgr = _mock_manager()
        with (
            patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await wf.async_run()

        assert wf.state.failed is True

    @pytest.mark.asyncio
    async def test_exception_calls_handle_workflow_error(self):
        """handle_workflow_error should be called with the exception."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)

        error = ValueError("bad config")
        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.side_effect = error

        mgr = _mock_manager()
        with (
            patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr),
            pytest.raises(ValueError, match="bad config"),
        ):
            await wf.async_run()

        wf.event_logger.handle_workflow_error.assert_called_once()
        call_args = wf.event_logger.handle_workflow_error.call_args
        assert call_args[0][0] is error
        assert "elapsed_time" in call_args[1]

    @pytest.mark.asyncio
    async def test_exception_reraises(self):
        """The original exception should be re-raised after error handling."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.side_effect = TypeError("type error")

        mgr = _mock_manager()
        with (
            patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr),
            pytest.raises(TypeError, match="type error"),
        ):
            await wf.async_run()

    @pytest.mark.asyncio
    async def test_exception_during_execute_level_async(self):
        """An exception from execute_level_async should be caught and reraised."""
        wf = _build_workflow()
        wf._resolve_upstream_and_initialize = MagicMock(return_value=True)

        orchestrator = wf.services.core.action_level_orchestrator
        orchestrator.compute_execution_levels.return_value = [["agent_a"]]
        orchestrator.execute_level_async = AsyncMock(side_effect=RuntimeError("level failed"))

        mgr = _mock_manager()
        with (
            patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr),
            pytest.raises(RuntimeError, match="level failed"),
        ):
            await wf.async_run()

        assert wf.state.failed is True
        wf.event_logger.handle_workflow_error.assert_called_once()


# ── _resolve_upstream_and_initialize ───────────────────────────────────


class TestResolveUpstreamAndInitialize:
    """Tests for the upstream resolution helper method."""

    def test_returns_true_when_upstream_succeeds(self):
        wf = _build_workflow()
        wf._resolve_upstream_workflows = MagicMock(return_value=True)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = wf._resolve_upstream_and_initialize()

        assert result is True

    def test_returns_false_when_upstream_pending(self):
        wf = _build_workflow()
        wf._resolve_upstream_workflows = MagicMock(return_value=False)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = wf._resolve_upstream_and_initialize()

        assert result is False

    def test_sets_manager_context(self):
        wf = _build_workflow()
        wf._resolve_upstream_workflows = MagicMock(return_value=True)

        mgr = _mock_manager()
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            wf._resolve_upstream_and_initialize()

        mgr.set_context.assert_called_once()
        call_kwargs = mgr.set_context.call_args[1]
        assert call_kwargs["workflow_name"] == "test_workflow"
        assert "correlation_id" in call_kwargs

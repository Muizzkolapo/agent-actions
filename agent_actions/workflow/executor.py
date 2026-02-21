"""
Single agent execution module.

Handles individual agent execution with batch support.
Extracted from agent_workflow.py to reduce run() method complexity.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Any, Optional
from rich.console import Console
from agent_actions.output.response.config_types import AgentConfigDict
from agent_actions.llm.providers.usage_tracker import get_last_usage
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    AgentSkipEvent,
    BatchSubmittedEvent,
    BatchCompleteEvent,
)
from agent_actions.errors import get_error_detail
from agent_actions.tooling.docs.run_tracker import ActionCompleteConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutorDependencies:
    """Dependencies for AgentExecutor."""

    agent_runner: Any
    state_manager: Any
    skip_evaluator: Any
    batch_manager: Any
    output_manager: Any

    def __repr__(self):
        """Return string representation."""
        return (
            f"{self.__class__.__name__}("
            f"agent_runner={self.agent_runner.__class__.__name__}, "
            f"state_manager={self.state_manager.__class__.__name__})"
        )


@dataclass
class ExecutionMetrics:
    """Metrics from agent execution."""

    duration: float = 0.0
    tokens: Optional[Dict[str, int]] = None
    model_vendor: Optional[str] = None
    model_name: Optional[str] = None
    files_processed: int = 0


@dataclass
class AgentRunParams:
    """Parameters for agent execution."""

    agent_name: str
    agent_idx: int
    agent_config: AgentConfigDict
    is_last_agent: bool
    start_time: datetime


@dataclass
class AgentExecutionResult:
    """Result of agent execution."""

    success: bool
    output_folder: Optional[str] = None
    status: str = "completed"  # 'completed', 'batch_submitted', 'failed'
    error: Optional[Exception] = None
    metrics: ExecutionMetrics = None

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.metrics is None:
            self.metrics = ExecutionMetrics()

    # Backward compatibility properties
    @property
    def duration(self) -> float:
        """Get duration from metrics."""
        return self.metrics.duration

    @property
    def tokens(self) -> Optional[Dict[str, int]]:
        """Get tokens from metrics."""
        return self.metrics.tokens

    @property
    def model_vendor(self) -> Optional[str]:
        """Get model_vendor from metrics."""
        return self.metrics.model_vendor

    @property
    def model_name(self) -> Optional[str]:
        """Get model_name from metrics."""
        return self.metrics.model_name

    @property
    def files_processed(self) -> int:
        """Get files_processed from metrics."""
        return self.metrics.files_processed

    def __repr__(self):
        """Return string representation."""
        return (
            f"AgentExecutionResult(success={self.success}, "
            f"status={self.status}, duration={self.metrics.duration:.2f})"
        )


class AgentExecutor:
    """
    Executes individual agents with full lifecycle management.

    Responsibilities:
    - Execute single agent (sync or async)
    - Handle batch mode detection and submission
    - Manage correlation setup
    """

    def __init__(self, deps: ExecutorDependencies, *, console: Optional[Console] = None):
        """
        Initialize agent executor.

        Args:
            deps: ExecutorDependencies with all required dependencies
            console: Rich console for output
        """
        self.deps = deps
        self.console = console or Console()

    def __eq__(self, other):
        """Check equality."""
        if not isinstance(other, AgentExecutor):
            return False
        return self.deps == other.deps

    def _verify_completion_status(self, agent_name: str) -> tuple:
        """
        Verify if a completed agent has actual output in storage.

        Args:
            agent_name: Name of the agent to verify

        Returns:
            Tuple of (should_skip: bool, result: Optional[AgentExecutionResult])
            - If should_skip is True, return the result
            - If should_skip is False, agent should be re-run
        """
        storage_backend = getattr(self.deps.agent_runner, "storage_backend", None)
        if storage_backend is not None:
            try:
                target_files = storage_backend.list_target_files(agent_name)
                if not target_files:
                    logger.info(
                        "Agent %s completed but no output in storage - re-running",
                        agent_name,
                    )
                    self.deps.state_manager.update_status(agent_name, "pending")
                    return (False, None)
                return (
                    True,
                    AgentExecutionResult(
                        success=True, status="completed", metrics=ExecutionMetrics(duration=0.0)
                    ),
                )
            except Exception as e:
                logger.warning("Failed to verify output for %s: %s", agent_name, e)
                return (
                    True,
                    AgentExecutionResult(
                        success=True, status="completed", metrics=ExecutionMetrics(duration=0.0)
                    ),
                )
        return (
            True,
            AgentExecutionResult(
                success=True, status="completed", metrics=ExecutionMetrics(duration=0.0)
            ),
        )

    def _handle_agent_skip(
        self, agent_name: str, agent_idx: int, agent_config: AgentConfigDict, start_time: datetime
    ) -> AgentExecutionResult:
        """
        Handle agent skip due to WHERE clause condition.

        Args:
            agent_name: Name of the agent
            agent_idx: Index in execution order
            agent_config: Agent configuration
            start_time: When execution started

        Returns:
            AgentExecutionResult indicating skip
        """
        self.deps.output_manager.create_passthrough_output(agent_idx, agent_name)
        self.deps.state_manager.update_status(agent_name, "completed")

        duration = (datetime.now() - start_time).total_seconds()
        total_agents = (
            len(self.deps.agent_runner.execution_order)
            if hasattr(self.deps.agent_runner, "execution_order")
            else 0
        )
        fire_event(
            AgentSkipEvent(
                agent_name=agent_name,
                agent_index=agent_idx,
                total_agents=total_agents,
                skip_reason="WHERE clause condition not met",
            )
        )

        if hasattr(self, "run_tracker") and hasattr(self, "run_id"):
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=agent_name,
                status="skipped",
                duration_seconds=duration,
                skip_reason="WHERE clause condition not met",
            )
            self.run_tracker.record_action_complete(config=config)

        return AgentExecutionResult(
            success=True, status="skipped", metrics=ExecutionMetrics(duration=duration)
        )

    def _track_action_start(self, params: AgentRunParams) -> None:
        """Track action start if run_tracker is available."""
        if hasattr(self, "run_tracker") and hasattr(self, "run_id"):
            # Determine action type from model_vendor or kind
            model_vendor = params.agent_config.get("model_vendor", "")
            action_kind = params.agent_config.get("kind", "")

            if model_vendor == "tool" or action_kind == "tool":
                action_type = "tool"
            elif model_vendor == "hitl" or action_kind == "hitl":
                action_type = "hitl"
            else:
                action_type = "llm"

            self.run_tracker.record_action_start(
                run_id=self.run_id,
                action_name=params.agent_name,
                action_type=action_type,
                agent_config=params.agent_config,
            )

    def _handle_run_success(
        self,
        params: AgentRunParams,
        output_folder: str,
        duration: float,
        batch_status: Optional[str],
    ) -> AgentExecutionResult:
        """
        Handle successful agent run result.

        Args:
            params: Agent run parameters
            output_folder: Output folder path
            duration: Execution duration in seconds
            batch_status: Status from batch submission check

        Returns:
            AgentExecutionResult
        """
        if batch_status == "batch_submitted":
            self.deps.state_manager.update_status(params.agent_name, "batch_submitted")
            fire_event(BatchSubmittedEvent(agent_name=params.agent_name))
            return AgentExecutionResult(
                success=True,
                status="batch_submitted",
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "passthrough":
            self.deps.state_manager.update_status(params.agent_name, "completed")
            logger.info(
                "Agent completed (passthrough)",
                extra={
                    "operation": "execute_agent_run",
                    "agent_name": params.agent_name,
                    "agent_idx": params.agent_idx,
                    "duration": duration,
                    "status": "passthrough",
                    "is_last_agent": params.is_last_agent,
                },
            )
            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status="completed",
                metrics=ExecutionMetrics(duration=duration),
            )

        # Normal completion
        self.deps.state_manager.update_status(params.agent_name, "completed")
        tokens = get_last_usage()

        if hasattr(self, "run_tracker") and hasattr(self, "run_id"):
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=params.agent_name,
                status="success",
                duration_seconds=duration,
                tokens=tokens,
                files_processed=0,
            )
            self.run_tracker.record_action_complete(config=config)

        return AgentExecutionResult(
            success=True,
            output_folder=output_folder,
            status="completed",
            metrics=ExecutionMetrics(
                duration=duration,
                tokens=tokens,
                model_vendor=params.agent_config.get("model_vendor"),
                model_name=params.agent_config.get("model_name"),
                files_processed=0,
            ),
        )

    def _handle_run_failure(self, params: AgentRunParams, error: Exception) -> AgentExecutionResult:
        """
        Handle agent run failure.

        Args:
            params: Agent run parameters
            error: The exception that occurred

        Returns:
            AgentExecutionResult indicating failure
        """
        duration = (datetime.now() - params.start_time).total_seconds()
        self.deps.state_manager.update_status(params.agent_name, "failed")

        if hasattr(self, "run_tracker") and hasattr(self, "run_id"):
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=params.agent_name,
                status="failed",
                duration_seconds=duration,
                error=get_error_detail(error),
            )
            self.run_tracker.record_action_complete(config=config)

        return AgentExecutionResult(
            success=False, status="failed", error=error, metrics=ExecutionMetrics(duration=duration)
        )

    def _cleanup_correlation(
        self, params: AgentRunParams, original_setup: Optional[Callable]
    ) -> None:
        """Restore original setup_directories after correlation setup."""
        if original_setup:
            try:
                self.deps.agent_runner.setup_directories = original_setup
            except (AttributeError, TypeError) as cleanup_error:
                logger.warning(
                    "Failed to restore original setup_directories",
                    extra={
                        "operation": "agent_cleanup",
                        "agent_name": params.agent_name,
                        "error": str(cleanup_error),
                    },
                )

    def execute_agent_sync(
        self, agent_name: str, *, agent_idx: int, agent_config: AgentConfigDict, is_last_agent: bool
    ) -> AgentExecutionResult:
        """
        Execute a single agent synchronously.

        Args:
            agent_name: Name of the agent
            agent_idx: Index in execution order
            agent_config: Agent configuration
            is_last_agent: Whether this is the last agent in workflow

        Returns:
            AgentExecutionResult with execution details
        """
        start_time = datetime.now()
        current_status = self.deps.state_manager.get_status(agent_name)

        logger.debug(
            "Agent execution starting",
            extra={
                "operation": "execute_agent_start",
                "agent_name": agent_name,
                "agent_idx": agent_idx,
                "current_status": current_status,
                "is_last_agent": is_last_agent,
            },
        )

        # Check 1: Already completed - verify output exists in storage backend
        if current_status == "completed":
            should_skip, result = self._verify_completion_status(agent_name)
            if should_skip:
                return result

        # Check 2: Batch job submitted, check status
        if current_status == "batch_submitted":
            return self._handle_batch_check(agent_name, agent_idx, agent_config, start_time)

        # Check 3: Should skip agent?
        previous_outputs = self.deps.output_manager.get_previous_outputs(agent_idx)
        if self.deps.skip_evaluator.should_skip_agent(agent_config, previous_outputs):
            return self._handle_agent_skip(agent_name, agent_idx, agent_config, start_time)

        # Execute the agent
        return self._execute_agent_run(
            AgentRunParams(
                agent_name=agent_name,
                agent_idx=agent_idx,
                agent_config=agent_config,
                is_last_agent=is_last_agent,
                start_time=start_time,
            )
        )

    async def execute_agent_async(
        self, agent_name: str, *, agent_idx: int, agent_config: AgentConfigDict, is_last_agent: bool
    ) -> AgentExecutionResult:
        """
        Execute a single agent asynchronously.

        Args:
            agent_name: Name of the agent
            agent_idx: Index in execution order
            agent_config: Agent configuration
            is_last_agent: Whether this is the last agent in workflow

        Returns:
            AgentExecutionResult with execution details
        """
        start_time = datetime.now()
        current_status = self.deps.state_manager.get_status(agent_name)

        logger.debug(
            "Agent execution starting",
            extra={
                "operation": "execute_agent_start",
                "agent_name": agent_name,
                "agent_idx": agent_idx,
                "current_status": current_status,
                "is_last_agent": is_last_agent,
            },
        )

        # Check 1: Already completed - verify output exists in storage backend
        if current_status == "completed":
            should_skip, result = self._verify_completion_status(agent_name)
            if should_skip:
                return result

        # Check 2: Batch job submitted, check status
        if current_status == "batch_submitted":
            return await self._handle_batch_check_async(
                agent_name, agent_idx, agent_config, start_time
            )

        # Check 3: Should skip agent?
        previous_outputs = self.deps.output_manager.get_previous_outputs(agent_idx)
        if self.deps.skip_evaluator.should_skip_agent(agent_config, previous_outputs):
            return self._handle_agent_skip(agent_name, agent_idx, agent_config, start_time)

        # Execute the agent
        return await self._execute_agent_run_async(
            AgentRunParams(
                agent_name=agent_name,
                agent_idx=agent_idx,
                agent_config=agent_config,
                is_last_agent=is_last_agent,
                start_time=start_time,
            )
        )

    def _handle_batch_check(
        self, agent_name: str, agent_idx: int, agent_config: AgentConfigDict, start_time: datetime
    ) -> AgentExecutionResult:
        """Handle batch job status checking (synchronous)."""
        self.deps.state_manager.update_status(agent_name, "checking_batch")
        workflow_name = self.deps.agent_runner.workflow_name
        agent_io_path = Path(self.deps.agent_runner.get_agent_folder(workflow_name))
        # Use simple directory name (no index prefix)
        output_directory = str(agent_io_path / "target" / agent_name)

        output_folder, batch_status = self.deps.batch_manager.handle_batch_agent(
            agent_name, output_directory, agent_config
        )

        duration = (datetime.now() - start_time).total_seconds()

        if batch_status == "completed":
            self.deps.state_manager.update_status(agent_name, "completed")
            fire_event(
                BatchCompleteEvent(
                    batch_id=agent_config.get("batch_id", ""),
                    agent_name=agent_name,
                    total=1,
                    completed=1,
                    failed=0,
                    elapsed_time=duration,
                )
            )
            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status="completed",
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "in_progress":
            self.deps.state_manager.update_status(agent_name, "batch_submitted")
            fire_event(
                BatchSubmittedEvent(
                    batch_id=agent_config.get("batch_id", ""),
                    agent_name=agent_name,
                    request_count=0,
                    provider=agent_config.get("model_vendor", ""),
                )
            )
            return AgentExecutionResult(
                success=True, status="batch_submitted", metrics=ExecutionMetrics(duration=duration)
            )

        self.deps.state_manager.update_status(agent_name, "failed")
        fire_event(
            BatchCompleteEvent(
                batch_id=agent_config.get("batch_id", ""),
                agent_name=agent_name,
                total=1,
                completed=0,
                failed=1,
                elapsed_time=duration,
            )
        )
        error = Exception(f"Batch job for {agent_name} failed")
        return AgentExecutionResult(
            success=False, status="failed", error=error, metrics=ExecutionMetrics(duration=duration)
        )

    async def _handle_batch_check_async(
        self, agent_name: str, agent_idx: int, agent_config: AgentConfigDict, start_time: datetime
    ) -> AgentExecutionResult:
        """Handle batch job status checking (asynchronous)."""
        self.deps.state_manager.update_status(agent_name, "checking_batch")
        workflow_name = self.deps.agent_runner.workflow_name
        agent_io_path = Path(self.deps.agent_runner.get_agent_folder(workflow_name))
        # Use simple directory name (no index prefix)
        output_directory = str(agent_io_path / "target" / agent_name)

        output_folder, batch_status = await asyncio.to_thread(
            self.deps.batch_manager.handle_batch_agent,
            agent_name,
            output_directory,
            agent_config,
        )

        duration = (datetime.now() - start_time).total_seconds()

        if batch_status == "completed":
            self.deps.state_manager.update_status(agent_name, "completed")
            # Fire batch complete event
            fire_event(
                BatchCompleteEvent(
                    batch_id=agent_config.get("batch_id", ""),
                    agent_name=agent_name,
                    total=1,
                    completed=1,
                    failed=0,
                    elapsed_time=duration,
                )
            )
            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status="completed",
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "in_progress":
            self.deps.state_manager.update_status(agent_name, "batch_submitted")
            # Fire batch submitted event (still in progress)
            fire_event(
                BatchSubmittedEvent(
                    batch_id=agent_config.get("batch_id", ""),
                    agent_name=agent_name,
                    request_count=0,  # Unknown at this point
                    provider=agent_config.get("model_vendor", ""),
                )
            )
            return AgentExecutionResult(
                success=True, status="batch_submitted", metrics=ExecutionMetrics(duration=duration)
            )

        self.deps.state_manager.update_status(agent_name, "failed")
        # Fire batch complete with failure
        fire_event(
            BatchCompleteEvent(
                batch_id=agent_config.get("batch_id", ""),
                agent_name=agent_name,
                total=1,
                completed=0,
                failed=1,
                elapsed_time=duration,
            )
        )
        error = Exception(f"Batch job for {agent_name} failed")
        return AgentExecutionResult(
            success=False, status="failed", error=error, metrics=ExecutionMetrics(duration=duration)
        )

    def _execute_agent_run(self, params: AgentRunParams) -> AgentExecutionResult:
        """Execute agent run (synchronous)."""
        self.deps.state_manager.update_status(params.agent_name, "running")
        self._track_action_start(params)
        original_setup = self._setup_correlation(params.agent_idx)

        try:
            output_folder = self.deps.agent_runner.run_agent(
                params.agent_config,
                params.agent_name,
                None,
                params.agent_idx,
            )
            duration = (datetime.now() - params.start_time).total_seconds()
            batch_status = self._check_batch_submission(params.agent_name, params.agent_idx)
            return self._handle_run_success(params, output_folder, duration, batch_status)

        except Exception as e:
            return self._handle_run_failure(params, e)

        finally:
            self._cleanup_correlation(params, original_setup)

    async def _execute_agent_run_async(self, params: AgentRunParams) -> AgentExecutionResult:
        """Execute agent run (asynchronous)."""
        self.deps.state_manager.update_status(params.agent_name, "running")
        self._track_action_start(params)
        original_setup = self._setup_correlation(params.agent_idx)

        try:
            output_folder = await asyncio.to_thread(
                self.deps.agent_runner.run_agent,
                params.agent_config,
                params.agent_name,
                None,
                params.agent_idx,
            )
            duration = (datetime.now() - params.start_time).total_seconds()
            batch_status = self._check_batch_submission(params.agent_name, params.agent_idx)
            return self._handle_run_success(params, output_folder, duration, batch_status)

        except Exception as e:
            return self._handle_run_failure(params, e)

        finally:
            self._cleanup_correlation(params, original_setup)

    def __repr__(self):
        """Return string representation."""
        return f"AgentExecutor(deps={self.deps})"

    def _setup_correlation(self, agent_idx: int) -> Optional[callable]:
        """Setup loop correlation if needed, return original setup function."""
        correlation_wrapper = self.deps.output_manager.setup_correlation_wrapper(agent_idx)

        if correlation_wrapper:
            original = self.deps.agent_runner.setup_directories
            self.deps.agent_runner.setup_directories = correlation_wrapper
            return original

        return None

    def _check_batch_submission(self, agent_name: str, agent_idx: int) -> Optional[str]:
        """Check if batch jobs were submitted."""
        workflow_name = self.deps.agent_runner.workflow_name
        agent_io_path = Path(self.deps.agent_runner.get_agent_folder(workflow_name))
        return self.deps.batch_manager.check_batch_submission(agent_name, agent_idx, agent_io_path)

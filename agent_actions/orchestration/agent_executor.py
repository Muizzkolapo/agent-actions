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
from typing import Dict, Any, Optional
from rich.console import Console
from agent_actions.llm_invocation.providers.usage_tracker import get_last_usage
from agent_actions.docs.run_tracker import ActionCompleteConfig

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
class AgentExecutionContext:
    """Context for executing an agent."""

    agent_name: str
    agent_idx: int
    agent_config: Dict[str, Any]
    is_last_agent: bool
    start_time: datetime


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
    agent_config: Dict[str, Any]
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

    def execute_agent_sync(
        self, agent_name: str, *, agent_idx: int, agent_config: Dict[str, Any], is_last_agent: bool
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

        # Check 1: Already completed
        if current_status == "completed":
            return AgentExecutionResult(
                success=True, status="completed", metrics=ExecutionMetrics(duration=0.0)
            )

        # Check 2: Batch job submitted, check status
        if current_status == "batch_submitted":
            return self._handle_batch_check(agent_name, agent_idx, agent_config, start_time)

        # Check 3: Should skip agent?
        previous_outputs = self.deps.output_manager.get_previous_outputs(agent_idx)
        if self.deps.skip_evaluator.should_skip_agent(agent_config, previous_outputs):
            self.console.print(f"Skipping agent {agent_name} due to WHERE clause condition")
            self.deps.output_manager.create_passthrough_output(agent_idx, agent_name)
            self.deps.state_manager.update_status(agent_name, "completed")

            # Track action skip
            duration = (datetime.now() - start_time).total_seconds()
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
                success=True, status="completed", metrics=ExecutionMetrics(duration=duration)
            )

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
        self, agent_name: str, *, agent_idx: int, agent_config: Dict[str, Any], is_last_agent: bool
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

        # Check 1: Already completed
        if current_status == "completed":
            return AgentExecutionResult(
                success=True, status="completed", metrics=ExecutionMetrics(duration=0.0)
            )

        # Check 2: Batch job submitted, check status
        if current_status == "batch_submitted":
            return await self._handle_batch_check_async(
                agent_name, agent_idx, agent_config, start_time
            )

        # Check 3: Should skip agent?
        previous_outputs = self.deps.output_manager.get_previous_outputs(agent_idx)
        if self.deps.skip_evaluator.should_skip_agent(agent_config, previous_outputs):
            self.console.print(f"  [yellow]Skipping {agent_name} (WHERE clause)[/yellow]")
            self.deps.output_manager.create_passthrough_output(agent_idx, agent_name)
            self.deps.state_manager.update_status(agent_name, "completed")

            # Track action skip
            duration = (datetime.now() - start_time).total_seconds()
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
                success=True, status="completed", metrics=ExecutionMetrics(duration=duration)
            )

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
        self, agent_name: str, agent_idx: int, agent_config: Dict[str, Any], start_time: datetime
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
            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status="completed",
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "in_progress":
            self.deps.state_manager.update_status(agent_name, "batch_submitted")
            return AgentExecutionResult(
                success=True, status="batch_submitted", metrics=ExecutionMetrics(duration=duration)
            )

        self.deps.state_manager.update_status(agent_name, "failed")
        error = Exception(f"Batch job for {agent_name} failed")
        return AgentExecutionResult(
            success=False, status="failed", error=error, metrics=ExecutionMetrics(duration=duration)
        )

    async def _handle_batch_check_async(
        self, agent_name: str, agent_idx: int, agent_config: Dict[str, Any], start_time: datetime
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
            agent_idx,
            output_directory,
            agent_config,
        )

        duration = (datetime.now() - start_time).total_seconds()

        if batch_status == "completed":
            self.deps.state_manager.update_status(agent_name, "completed")
            self.console.print(
                f"  [green]✓ {agent_name} (batch completed, {duration:.2f}s)[/green]"
            )
            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status="completed",
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "in_progress":
            self.deps.state_manager.update_status(agent_name, "batch_submitted")
            self.console.print(
                f"  [yellow]→ {agent_name}: batch still in progress ({duration:.2f}s)[/yellow]"
            )
            return AgentExecutionResult(
                success=True, status="batch_submitted", metrics=ExecutionMetrics(duration=duration)
            )

        self.deps.state_manager.update_status(agent_name, "failed")
        self.console.print(f"  [red]✗ {agent_name}: batch failed ({duration:.2f}s)[/red]")
        error = Exception(f"Batch job for {agent_name} failed")
        return AgentExecutionResult(
            success=False, status="failed", error=error, metrics=ExecutionMetrics(duration=duration)
        )

    def _execute_agent_run(self, params: AgentRunParams) -> AgentExecutionResult:
        """Execute agent run (synchronous)."""
        self.deps.state_manager.update_status(params.agent_name, "running")

        # Track action start
        if hasattr(self, "run_tracker") and hasattr(self, "run_id"):
            action_type = "tool" if params.agent_config.get("model_vendor") == "tool" else "llm"
            self.run_tracker.record_action_start(
                run_id=self.run_id,
                action_name=params.agent_name,
                action_type=action_type,
                agent_config=params.agent_config,
            )

        # Setup correlation if needed
        original_setup = self._setup_correlation(params.agent_idx)

        try:
            # Run the agent
            output_folder = self.deps.agent_runner.run_agent(
                params.agent_config,
                params.agent_name,
                None,  # previous_agent_type not needed with new setup
                params.agent_idx,
                params.is_last_agent,
            )

            duration = (datetime.now() - params.start_time).total_seconds()

            # Check if batch mode
            batch_status = self._check_batch_submission(params.agent_name, params.agent_idx)
            if batch_status == "batch_submitted":
                self.deps.state_manager.update_status(params.agent_name, "batch_submitted")
                logger.info(
                    "Agent batch submitted",
                    extra={
                        "operation": "execute_agent_run",
                        "agent_name": params.agent_name,
                        "agent_idx": params.agent_idx,
                        "duration": duration,
                        "status": "batch_submitted",
                        "is_last_agent": params.is_last_agent,
                    },
                )
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
            logger.info(
                "Agent completed successfully",
                extra={
                    "operation": "execute_agent_run",
                    "agent_name": params.agent_name,
                    "agent_idx": params.agent_idx,
                    "duration": duration,
                    "status": "completed",
                    "is_last_agent": params.is_last_agent,
                },
            )

            # Retrieve token usage from thread-local storage
            tokens = get_last_usage()

            # Track action success
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

        except (
            OSError,
            IOError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            AttributeError,
        ) as e:
            duration = (datetime.now() - params.start_time).total_seconds()
            logger.debug(
                "Agent execution failed",
                extra={
                    "operation": "execute_agent_run",
                    "agent_name": params.agent_name,
                    "agent_idx": params.agent_idx,
                    "duration": duration,
                    "is_last_agent": params.is_last_agent,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            self.deps.state_manager.update_status(params.agent_name, "failed")

            # Track action failure
            if hasattr(self, "run_tracker") and hasattr(self, "run_id"):
                config = ActionCompleteConfig(
                    run_id=self.run_id,
                    action_name=params.agent_name,
                    status="failed",
                    duration_seconds=duration,
                    error=str(e),
                )
                self.run_tracker.record_action_complete(config=config)

            return AgentExecutionResult(
                success=False, status="failed", error=e, metrics=ExecutionMetrics(duration=duration)
            )

        finally:
            # Restore original setup
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

    async def _execute_agent_run_async(self, params: AgentRunParams) -> AgentExecutionResult:
        """Execute agent run (asynchronous)."""
        self.deps.state_manager.update_status(params.agent_name, "running")

        # Track action start
        if hasattr(self, "run_tracker") and hasattr(self, "run_id"):
            action_type = "tool" if params.agent_config.get("model_vendor") == "tool" else "llm"
            self.run_tracker.record_action_start(
                run_id=self.run_id,
                action_name=params.agent_name,
                action_type=action_type,
                agent_config=params.agent_config,
            )

        # Setup correlation if needed
        original_setup = self._setup_correlation(params.agent_idx)

        try:
            # Run the agent in thread pool
            output_folder = await asyncio.to_thread(
                self.deps.agent_runner.run_agent,
                params.agent_config,
                params.agent_name,
                None,
                params.agent_idx,
                params.is_last_agent,
            )

            duration = (datetime.now() - params.start_time).total_seconds()

            # Check if batch mode
            batch_status = self._check_batch_submission(params.agent_name, params.agent_idx)
            if batch_status == "batch_submitted":
                self.deps.state_manager.update_status(params.agent_name, "batch_submitted")
                self.console.print(f"  [yellow]→ {params.agent_name}: batch submitted[/yellow]")
                logger.info(
                    "Agent batch submitted (async)",
                    extra={
                        "operation": "execute_agent_run_async",
                        "agent_name": params.agent_name,
                        "agent_idx": params.agent_idx,
                        "duration": duration,
                        "status": "batch_submitted",
                        "is_last_agent": params.is_last_agent,
                    },
                )
                return AgentExecutionResult(
                    success=True,
                    status="batch_submitted",
                    metrics=ExecutionMetrics(duration=duration),
                )

            # Normal completion
            self.deps.state_manager.update_status(params.agent_name, "completed")
            self.console.print(f"  [green]✓ {params.agent_name} ({duration:.2f}s)[/green]")
            logger.info(
                "Agent completed successfully (async)",
                extra={
                    "operation": "execute_agent_run_async",
                    "agent_name": params.agent_name,
                    "agent_idx": params.agent_idx,
                    "duration": duration,
                    "status": "completed",
                    "is_last_agent": params.is_last_agent,
                },
            )

            # Retrieve token usage from thread-local storage
            tokens = get_last_usage()

            # Track action success
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

        except (
            OSError,
            IOError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            AttributeError,
        ) as e:
            duration = (datetime.now() - params.start_time).total_seconds()
            logger.exception(
                "Async agent execution failed",
                extra={
                    "operation": "execute_agent_run_async",
                    "agent_name": params.agent_name,
                    "agent_idx": params.agent_idx,
                    "duration": duration,
                    "is_last_agent": params.is_last_agent,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            self.console.print(f"  [red]✗ {params.agent_name} failed: {e}[/red]")
            self.deps.state_manager.update_status(params.agent_name, "failed")

            # Track action failure
            if hasattr(self, "run_tracker") and hasattr(self, "run_id"):
                config = ActionCompleteConfig(
                    run_id=self.run_id,
                    action_name=params.agent_name,
                    status="failed",
                    duration_seconds=duration,
                    error=str(e),
                )
                self.run_tracker.record_action_complete(config=config)

            return AgentExecutionResult(
                success=False, status="failed", error=e, metrics=ExecutionMetrics(duration=duration)
            )

        finally:
            # Restore original setup
            if original_setup:
                try:
                    self.deps.agent_runner.setup_directories = original_setup
                except (AttributeError, TypeError) as cleanup_error:
                    logger.warning(
                        "Failed to restore original setup_directories",
                        extra={
                            "operation": "agent_cleanup_async",
                            "agent_name": params.agent_name,
                            "error": str(cleanup_error),
                        },
                    )

    def __repr__(self):
        """Return string representation."""
        return f"AgentExecutor(deps={self.deps})"

    def _setup_correlation(self, agent_idx: int) -> Optional[callable]:
        """Setup loop correlation if needed, return original setup function."""
        correlation_wrapper = self.deps.output_manager.setup_correlation_wrapper(
            agent_idx, self.deps.agent_runner.setup_directories
        )

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

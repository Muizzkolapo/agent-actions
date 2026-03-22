"""Single action execution with batch support."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from rich.console import Console

from agent_actions.config.types import ActionConfigDict
from agent_actions.errors import get_error_detail
from agent_actions.llm.providers.usage_tracker import get_last_usage
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    ActionSkipEvent,
    BatchCompleteEvent,
    BatchSubmittedEvent,
)
from agent_actions.tooling.docs.run_tracker import ActionCompleteConfig
from agent_actions.utils.constants import DEFAULT_ACTION_KIND

logger = logging.getLogger(__name__)


@dataclass
class ExecutorDependencies:
    """Dependencies for ActionExecutor."""

    action_runner: Any
    state_manager: Any
    skip_evaluator: Any
    batch_manager: Any
    output_manager: Any

    def __repr__(self):
        return (
            f"{self.__class__.__name__}("
            f"action_runner={self.action_runner.__class__.__name__}, "
            f"state_manager={self.state_manager.__class__.__name__})"
        )


@dataclass
class ExecutionMetrics:
    """Metrics from action execution."""

    duration: float = 0.0
    tokens: dict[str, int] | None = None
    model_vendor: str | None = None
    model_name: str | None = None
    files_processed: int = 0


@dataclass
class ActionRunParams:
    """Parameters for action execution."""

    action_name: str
    action_idx: int
    action_config: ActionConfigDict
    is_last_action: bool
    start_time: datetime


@dataclass
class ActionExecutionResult:
    """Result of action execution."""

    success: bool
    output_folder: str | None = None
    status: str = "completed"  # 'completed', 'batch_submitted', 'failed'
    error: Exception | None = None
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)

    def __post_init__(self) -> None:
        # Defensive: coerce None back to default if a caller passes metrics=None
        if self.metrics is None:  # type: ignore[comparison-overlap]  # defensive
            object.__setattr__(self, "metrics", ExecutionMetrics())  # type: ignore[unreachable]

    # Backward compatibility properties
    @property
    def duration(self) -> float:
        """Return duration from metrics."""
        return self.metrics.duration

    @property
    def tokens(self) -> dict[str, int] | None:
        """Return tokens from metrics."""
        return self.metrics.tokens

    @property
    def model_vendor(self) -> str | None:
        """Return model_vendor from metrics."""
        return self.metrics.model_vendor

    @property
    def model_name(self) -> str | None:
        """Return model_name from metrics."""
        return self.metrics.model_name

    @property
    def files_processed(self) -> int:
        """Return files_processed from metrics."""
        return self.metrics.files_processed

    def __repr__(self):
        return (
            f"ActionExecutionResult(success={self.success}, "
            f"status={self.status}, duration={self.metrics.duration:.2f})"
        )


class ActionExecutor:
    """Executes individual actions with full lifecycle management."""

    def __init__(self, deps: ExecutorDependencies, *, console: Console | None = None):
        """Initialize action executor."""
        self.deps = deps
        self.console = console or Console()
        self.run_tracker: Any | None = None
        self.run_id: str | None = None

    def __eq__(self, other):
        if not isinstance(other, ActionExecutor):
            return False
        return self.deps == other.deps

    def verify_completion_status(self, action_name: str) -> bool:
        """Return True if the action has valid output and should be skipped.

        Resets to 'pending' (and returns False) if the action is marked
        completed but has no output in the storage backend.  Called from
        the level executor before filtering pending actions so that stale
        'completed' upstreams are re-run before their dependents need them.
        """
        should_skip, _ = self._verify_completion_status(action_name)
        return should_skip

    def _verify_completion_status(
        self, action_name: str
    ) -> tuple[bool, ActionExecutionResult | None]:
        """Verify a completed action has actual output in storage.

        Returns:
            (should_skip, result) -- if should_skip is False, agent is re-run.
        """
        storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
        if storage_backend is not None:
            try:
                target_files = storage_backend.list_target_files(action_name)
                if not target_files:
                    logger.info(
                        "Action %s completed but no output in storage - re-running",
                        action_name,
                    )
                    self.deps.state_manager.update_status(action_name, "pending")
                    return (False, None)
                return (
                    True,
                    ActionExecutionResult(
                        success=True, status="completed", metrics=ExecutionMetrics(duration=0.0)
                    ),
                )
            except Exception as e:
                logger.warning(
                    "Failed to verify output for %s, resetting to pending: %s",
                    action_name,
                    e,
                    exc_info=True,
                )
                self.deps.state_manager.update_status(action_name, "pending")
                return (False, None)
        return (
            True,
            ActionExecutionResult(
                success=True, status="completed", metrics=ExecutionMetrics(duration=0.0)
            ),
        )

    def _handle_action_skip(
        self,
        action_name: str,
        action_idx: int,
        action_config: ActionConfigDict,
        start_time: datetime,
    ) -> ActionExecutionResult:
        """Handle action skip due to WHERE clause condition."""
        self.deps.output_manager.create_passthrough_output(action_idx, action_name)
        self.deps.state_manager.update_status(action_name, "completed")

        duration = (datetime.now() - start_time).total_seconds()
        total_actions = (
            len(self.deps.action_runner.execution_order)
            if hasattr(self.deps.action_runner, "execution_order")
            else 0
        )
        fire_event(
            ActionSkipEvent(
                action_name=action_name,
                action_index=action_idx,
                total_actions=total_actions,
                skip_reason="WHERE clause condition not met",
            )
        )

        if self.run_tracker is not None and self.run_id is not None:
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=action_name,
                status="skipped",
                duration_seconds=duration,
                skip_reason="WHERE clause condition not met",
            )
            self.run_tracker.record_action_complete(config=config)

        return ActionExecutionResult(
            success=True, status="skipped", metrics=ExecutionMetrics(duration=duration)
        )

    def _track_action_start(self, params: ActionRunParams) -> None:
        """Track action start if run_tracker is available."""
        if self.run_tracker is not None and self.run_id is not None:
            model_vendor = params.action_config.get("model_vendor", "")
            action_kind = params.action_config.get("kind", "")

            if model_vendor == "tool" or action_kind == "tool":
                action_type = "tool"
            elif model_vendor == "hitl" or action_kind == "hitl":
                action_type = "hitl"
            else:
                action_type = DEFAULT_ACTION_KIND

            self.run_tracker.record_action_start(
                run_id=self.run_id,
                action_name=params.action_name,
                action_type=action_type,
                action_config=params.action_config,
            )

    def _handle_run_success(
        self,
        params: ActionRunParams,
        output_folder: str,
        duration: float,
        batch_status: str | None,
    ) -> ActionExecutionResult:
        """Handle successful action run result."""
        if batch_status == "batch_submitted":
            self.deps.state_manager.update_status(params.action_name, "batch_submitted")
            fire_event(BatchSubmittedEvent(action_name=params.action_name))
            return ActionExecutionResult(
                success=True,
                status="batch_submitted",
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "passthrough":
            self.deps.state_manager.update_status(params.action_name, "completed")
            logger.info(
                "Action completed (passthrough)",
                extra={
                    "operation": "execute_action_run",
                    "action_name": params.action_name,
                    "action_idx": params.action_idx,
                    "duration": duration,
                    "status": "passthrough",
                    "is_last_action": params.is_last_action,
                },
            )
            return ActionExecutionResult(
                success=True,
                output_folder=output_folder,
                status="completed",
                metrics=ExecutionMetrics(duration=duration),
            )

        # Normal completion
        self.deps.state_manager.update_status(params.action_name, "completed")
        tokens = get_last_usage()

        if self.run_tracker is not None and self.run_id is not None:
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=params.action_name,
                status="success",
                duration_seconds=duration,
                tokens=tokens,
                files_processed=0,
            )
            self.run_tracker.record_action_complete(config=config)

        return ActionExecutionResult(
            success=True,
            output_folder=output_folder,
            status="completed",
            metrics=ExecutionMetrics(
                duration=duration,
                tokens=tokens,
                model_vendor=params.action_config.get("model_vendor"),
                model_name=params.action_config.get("model_name"),
                files_processed=0,
            ),
        )

    def _handle_run_failure(
        self, params: ActionRunParams, error: Exception
    ) -> ActionExecutionResult:
        """Handle action run failure."""
        duration = (datetime.now() - params.start_time).total_seconds()
        self.deps.state_manager.update_status(params.action_name, "failed")

        if self.run_tracker is not None and self.run_id is not None:
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=params.action_name,
                status="failed",
                duration_seconds=duration,
                error=get_error_detail(error),
            )
            self.run_tracker.record_action_complete(config=config)

        return ActionExecutionResult(
            success=False, status="failed", error=error, metrics=ExecutionMetrics(duration=duration)
        )

    def _cleanup_correlation(
        self, params: ActionRunParams, original_setup: Callable | None
    ) -> None:
        """Restore original setup_directories after correlation setup."""
        if original_setup:
            try:
                self.deps.action_runner.setup_directories = original_setup
            except (AttributeError, TypeError) as cleanup_error:
                logger.warning(
                    "Failed to restore original setup_directories",
                    extra={
                        "operation": "action_cleanup",
                        "action_name": params.action_name,
                        "error": str(cleanup_error),
                    },
                )

    def execute_action_sync(
        self,
        action_name: str,
        *,
        action_idx: int,
        action_config: ActionConfigDict,
        is_last_action: bool,
    ) -> ActionExecutionResult:
        """Execute a single action synchronously."""
        start_time = datetime.now()
        current_status = self.deps.state_manager.get_status(action_name)

        logger.debug(
            "Action execution starting",
            extra={
                "operation": "execute_action_start",
                "action_name": action_name,
                "action_idx": action_idx,
                "current_status": current_status,
                "is_last_action": is_last_action,
            },
        )

        if current_status == "completed":
            should_skip, result = self._verify_completion_status(action_name)
            if should_skip:
                if result is None:
                    raise RuntimeError(
                        f"Action '{action_name}' marked completed but _verify_completion_status returned no result"
                    )
                return result
            current_status = self.deps.state_manager.get_status(action_name)

        if current_status == "batch_submitted":
            return self._handle_batch_check(action_name, action_idx, action_config, start_time)

        previous_outputs = self.deps.output_manager.get_previous_outputs(action_idx)
        if self.deps.skip_evaluator.should_skip_action(action_config, previous_outputs):
            return self._handle_action_skip(action_name, action_idx, action_config, start_time)

        return self._execute_action_run(
            ActionRunParams(
                action_name=action_name,
                action_idx=action_idx,
                action_config=action_config,
                is_last_action=is_last_action,
                start_time=start_time,
            )
        )

    async def execute_action_async(
        self,
        action_name: str,
        *,
        action_idx: int,
        action_config: ActionConfigDict,
        is_last_action: bool,
    ) -> ActionExecutionResult:
        """Execute a single action asynchronously."""
        start_time = datetime.now()
        current_status = self.deps.state_manager.get_status(action_name)

        logger.debug(
            "Action execution starting",
            extra={
                "operation": "execute_action_start",
                "action_name": action_name,
                "action_idx": action_idx,
                "current_status": current_status,
                "is_last_action": is_last_action,
            },
        )

        if current_status == "completed":
            should_skip, result = self._verify_completion_status(action_name)
            if should_skip:
                if result is None:
                    raise RuntimeError(
                        f"Action '{action_name}' marked completed but _verify_completion_status returned no result"
                    )
                return result
            current_status = self.deps.state_manager.get_status(action_name)

        if current_status == "batch_submitted":
            return await self._handle_batch_check_async(
                action_name, action_idx, action_config, start_time
            )

        previous_outputs = self.deps.output_manager.get_previous_outputs(action_idx)
        if self.deps.skip_evaluator.should_skip_action(action_config, previous_outputs):
            return self._handle_action_skip(action_name, action_idx, action_config, start_time)

        return await self._execute_action_run_async(
            ActionRunParams(
                action_name=action_name,
                action_idx=action_idx,
                action_config=action_config,
                is_last_action=is_last_action,
                start_time=start_time,
            )
        )

    def _handle_batch_check(
        self,
        action_name: str,
        action_idx: int,
        action_config: ActionConfigDict,
        start_time: datetime,
    ) -> ActionExecutionResult:
        """Handle batch job status checking (synchronous)."""
        self.deps.state_manager.update_status(action_name, "checking_batch")
        workflow_name = self.deps.action_runner.workflow_name
        agent_io_path = Path(self.deps.action_runner.get_action_folder(workflow_name))
        output_directory = str(agent_io_path / "target" / action_name)

        output_folder, batch_status = self.deps.batch_manager.handle_batch_agent(
            action_name, output_directory, action_config
        )

        duration = (datetime.now() - start_time).total_seconds()

        if batch_status == "completed":
            self.deps.state_manager.update_status(action_name, "completed")
            fire_event(
                BatchCompleteEvent(
                    batch_id=action_config.get("batch_id", ""),
                    action_name=action_name,
                    total=1,
                    completed=1,
                    failed=0,
                    elapsed_time=duration,
                )
            )
            return ActionExecutionResult(
                success=True,
                output_folder=output_folder,
                status="completed",
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "in_progress":
            self.deps.state_manager.update_status(action_name, "batch_submitted")
            fire_event(
                BatchSubmittedEvent(
                    batch_id=action_config.get("batch_id", ""),
                    action_name=action_name,
                    request_count=0,
                    provider=action_config.get("model_vendor", ""),
                )
            )
            return ActionExecutionResult(
                success=True, status="batch_submitted", metrics=ExecutionMetrics(duration=duration)
            )

        self.deps.state_manager.update_status(action_name, "failed")
        fire_event(
            BatchCompleteEvent(
                batch_id=action_config.get("batch_id", ""),
                action_name=action_name,
                total=1,
                completed=0,
                failed=1,
                elapsed_time=duration,
            )
        )
        error = Exception(f"Batch job for {action_name} failed")
        return ActionExecutionResult(
            success=False, status="failed", error=error, metrics=ExecutionMetrics(duration=duration)
        )

    async def _handle_batch_check_async(
        self,
        action_name: str,
        action_idx: int,
        action_config: ActionConfigDict,
        start_time: datetime,
    ) -> ActionExecutionResult:
        """Handle batch job status checking (asynchronous)."""
        self.deps.state_manager.update_status(action_name, "checking_batch")
        workflow_name = self.deps.action_runner.workflow_name
        agent_io_path = Path(self.deps.action_runner.get_action_folder(workflow_name))
        output_directory = str(agent_io_path / "target" / action_name)

        output_folder, batch_status = await asyncio.to_thread(
            self.deps.batch_manager.handle_batch_agent,
            action_name,
            output_directory,
            action_config,
        )

        duration = (datetime.now() - start_time).total_seconds()

        if batch_status == "completed":
            self.deps.state_manager.update_status(action_name, "completed")
            fire_event(
                BatchCompleteEvent(
                    batch_id=action_config.get("batch_id", ""),
                    action_name=action_name,
                    total=1,
                    completed=1,
                    failed=0,
                    elapsed_time=duration,
                )
            )
            return ActionExecutionResult(
                success=True,
                output_folder=output_folder,
                status="completed",
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "in_progress":
            self.deps.state_manager.update_status(action_name, "batch_submitted")
            fire_event(
                BatchSubmittedEvent(
                    batch_id=action_config.get("batch_id", ""),
                    action_name=action_name,
                    request_count=0,
                    provider=action_config.get("model_vendor", ""),
                )
            )
            return ActionExecutionResult(
                success=True, status="batch_submitted", metrics=ExecutionMetrics(duration=duration)
            )

        self.deps.state_manager.update_status(action_name, "failed")
        fire_event(
            BatchCompleteEvent(
                batch_id=action_config.get("batch_id", ""),
                action_name=action_name,
                total=1,
                completed=0,
                failed=1,
                elapsed_time=duration,
            )
        )
        error = Exception(f"Batch job for {action_name} failed")
        return ActionExecutionResult(
            success=False, status="failed", error=error, metrics=ExecutionMetrics(duration=duration)
        )

    def _execute_action_run(self, params: ActionRunParams) -> ActionExecutionResult:
        """Execute action run (synchronous)."""
        self.deps.state_manager.update_status(params.action_name, "running")
        self._track_action_start(params)
        original_setup = self._setup_correlation(params.action_idx)

        try:
            output_folder = self.deps.action_runner.run_action(
                params.action_config,
                params.action_name,
                None,
                params.action_idx,
            )
            duration = (datetime.now() - params.start_time).total_seconds()
            batch_status = self._check_batch_submission(params.action_name, params.action_idx)
            return self._handle_run_success(params, output_folder, duration, batch_status)

        except Exception as e:
            return self._handle_run_failure(params, e)

        finally:
            self._cleanup_correlation(params, original_setup)

    async def _execute_action_run_async(self, params: ActionRunParams) -> ActionExecutionResult:
        """Execute action run (asynchronous)."""
        self.deps.state_manager.update_status(params.action_name, "running")
        self._track_action_start(params)
        original_setup = self._setup_correlation(params.action_idx)

        try:
            output_folder = await asyncio.to_thread(
                self.deps.action_runner.run_action,
                params.action_config,
                params.action_name,
                None,
                params.action_idx,
            )
            duration = (datetime.now() - params.start_time).total_seconds()
            batch_status = self._check_batch_submission(params.action_name, params.action_idx)
            return self._handle_run_success(params, output_folder, duration, batch_status)

        except Exception as e:
            return self._handle_run_failure(params, e)

        finally:
            self._cleanup_correlation(params, original_setup)

    def __repr__(self):
        return f"ActionExecutor(deps={self.deps})"

    def _setup_correlation(self, action_idx: int) -> Callable | None:
        """Setup loop correlation if needed, return original setup function."""
        correlation_wrapper = self.deps.output_manager.setup_correlation_wrapper(action_idx)

        if correlation_wrapper:
            original = self.deps.action_runner.setup_directories
            self.deps.action_runner.setup_directories = correlation_wrapper
            return cast(Callable, original)

        return None

    def _check_batch_submission(self, action_name: str, action_idx: int) -> str | None:
        """Check if batch jobs were submitted."""
        workflow_name = self.deps.action_runner.workflow_name
        agent_io_path = Path(self.deps.action_runner.get_action_folder(workflow_name))
        return cast(
            str | None,
            self.deps.batch_manager.check_batch_submission(action_name, action_idx, agent_io_path),
        )

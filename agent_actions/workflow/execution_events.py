"""Workflow event firing and logging."""

import logging
from datetime import datetime

from agent_actions.errors import get_error_detail
from agent_actions.logging.core.manager import fire_event, get_manager
from agent_actions.logging.events import (
    ActionCompleteEvent,
    ActionFailedEvent,
    ActionSkipEvent,
    ActionStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    WorkflowStartEvent,
)
from agent_actions.workflow.managers.state import COMPLETED_STATUSES
from agent_actions.workflow.models import ActionLogParams, WorkflowRuntimeConfig, WorkflowServices

logger = logging.getLogger(__name__)


class WorkflowEventLogger:
    """Encapsulates all event-firing and structured logging for a workflow run."""

    def __init__(
        self,
        agent_name: str,
        execution_order: list,
        config: "WorkflowRuntimeConfig",
        services: "WorkflowServices",
    ):
        self.agent_name = agent_name
        self.execution_order = execution_order
        self.config = config
        self.services = services

    def log_workflow_start(self, workflow_start: datetime, is_async: bool = False):
        """Log workflow start with session separator."""
        correlation_id = get_manager().get_context("correlation_id")
        time_str = workflow_start.strftime("%H:%M:%S.%f")[:-3]
        corr_id = correlation_id[:8] if correlation_id else "unknown"
        separator = f"====== {time_str} | {corr_id} ======"
        logger.debug(separator)

        mode = "async" if is_async else "sequential"

        fire_event(
            WorkflowStartEvent(
                workflow_name=self.agent_name,
                action_count=len(self.execution_order),
                execution_mode=mode,
            )
        )

        logger.debug(
            "Workflow started (%s)",
            mode,
            extra={
                "operation": f"workflow_start_{mode}",
                "workflow_name": self.agent_name,
                "action_count": len(self.execution_order),
            },
        )

    def fire_action_start(
        self, idx: int, action_name: str, total_actions: int, action_config: dict
    ):
        """Fire an ActionStartEvent."""
        fire_event(
            ActionStartEvent(
                action_name=action_name,
                action_index=idx,
                total_actions=total_actions,
                action_type=action_config.get("type", ""),
                mode=action_config.get("run_mode", ""),
            )
        )

    def log_action_skip(self, idx: int, action_name: str, total_actions: int, run_mode: str = ""):
        """Log skipped action."""
        fire_event(
            ActionSkipEvent(
                action_name=action_name,
                action_index=idx,
                total_actions=total_actions,
                skip_reason="already completed",
                mode=run_mode,
            )
        )

    def log_action_result(self, params: ActionLogParams):
        """Log action execution result via event system."""
        if params.result.success and params.result.status in COMPLETED_STATUSES:
            tokens = {}
            if hasattr(params.result, "tokens") and params.result.tokens:
                tokens = params.result.tokens
            fire_event(
                ActionCompleteEvent(
                    action_name=params.action_name,
                    action_index=params.idx,
                    total_actions=params.total_actions,
                    execution_time=params.duration,
                    output_path=params.result.output_folder or "",
                    tokens=tokens,
                    mode=params.run_mode,
                )
            )
        elif not params.result.success:
            fire_event(
                ActionFailedEvent(
                    action_name=params.action_name,
                    action_index=params.idx,
                    total_actions=params.total_actions,
                    error_message=str(params.result.error) if params.result.error else "",
                    error_detail=get_error_detail(params.result.error)
                    if params.result.error
                    else "",
                    error_type=type(params.result.error).__name__ if params.result.error else "",
                    execution_time=params.duration,
                    mode=params.run_mode,
                )
            )
        # batch_submitted: BatchSubmittedEvent already fired by executor

    def finalize_workflow(self, elapsed_time: float = 0.0):
        """Finalize workflow execution."""
        summary = self.services.core.state_manager.get_summary()

        fire_event(
            WorkflowCompleteEvent(
                workflow_name=self.agent_name,
                elapsed_time=elapsed_time,
                actions_completed=summary.get("completed", 0),
                actions_partial=summary.get("completed_with_failures", 0),
                actions_skipped=summary.get("skipped", 0),
                actions_failed=summary.get("failed", 0),
            )
        )

        if self.services.support.manifest_manager:
            self.services.support.manifest_manager.mark_workflow_completed()

    def handle_workflow_error(self, error: Exception, elapsed_time: float = 0.0):
        """Handle workflow execution error with structured output."""
        fire_event(
            WorkflowFailedEvent(
                workflow_name=self.agent_name,
                error_message=str(error),
                error_detail=get_error_detail(error),
                error_type=type(error).__name__,
                elapsed_time=elapsed_time,
                failed_action=get_manager().get_context("action_name") or "",
            )
        )

        if self.services.support.manifest_manager:
            self.services.support.manifest_manager.mark_workflow_failed(get_error_detail(error))

        self.services.core.state_manager.mark_running_as_failed()

        # CLI decorator checks this attribute to prevent duplicate output
        error._already_displayed = True  # type: ignore[attr-defined]

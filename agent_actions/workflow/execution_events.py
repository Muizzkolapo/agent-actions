"""Workflow event firing and logging."""

import logging
from datetime import datetime

from agent_actions.errors import get_error_detail
from agent_actions.logging import fire_event, get_manager
from agent_actions.logging.events import (
    AgentCompleteEvent,
    AgentFailedEvent,
    AgentSkipEvent,
    AgentStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    WorkflowStartEvent,
)
from agent_actions.workflow.models import AgentLogParams, WorkflowConfig, WorkflowServices

logger = logging.getLogger(__name__)


class WorkflowEventLogger:
    """Encapsulates all event-firing and structured logging for a workflow run."""

    def __init__(
        self,
        agent_name: str,
        execution_order: list,
        config: "WorkflowConfig",
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
        logger.info(separator)

        mode = "async" if is_async else "sequential"

        fire_event(
            WorkflowStartEvent(
                workflow_name=self.agent_name,
                agent_count=len(self.execution_order),
                execution_mode=mode,
                run_upstream=self.config.run_upstream,
                run_downstream=self.config.run_downstream,
            )
        )

        logger.info(
            "Workflow started (%s)",
            mode,
            extra={
                "operation": f"workflow_start_{mode}",
                "workflow_name": self.agent_name,
                "agent_count": len(self.execution_order),
            },
        )

    def fire_agent_start(self, idx: int, agent_name: str, total_agents: int, agent_config: dict):
        """Fire an AgentStartEvent."""
        fire_event(
            AgentStartEvent(
                agent_name=agent_name,
                agent_index=idx,
                total_agents=total_agents,
                agent_type=agent_config.get("type", ""),
            )
        )

    def log_agent_skip(self, idx: int, agent_name: str, total_agents: int):
        """Log skipped agent."""
        fire_event(
            AgentSkipEvent(
                agent_name=agent_name,
                agent_index=idx,
                total_agents=total_agents,
                skip_reason="already completed",
            )
        )

    def log_agent_result(self, params: AgentLogParams):
        """Log agent execution result via event system."""
        if params.result.success and params.result.status == "completed":
            tokens = {}
            if hasattr(params.result, "tokens") and params.result.tokens:
                tokens = params.result.tokens
            fire_event(
                AgentCompleteEvent(
                    agent_name=params.agent_name,
                    agent_index=params.idx,
                    total_agents=params.total_agents,
                    execution_time=params.duration,
                    output_path=params.result.output_folder or "",
                    tokens=tokens,
                )
            )
        elif not params.result.success:
            fire_event(
                AgentFailedEvent(
                    agent_name=params.agent_name,
                    agent_index=params.idx,
                    total_agents=params.total_agents,
                    error_message=str(params.result.error) if params.result.error else "",
                    error_detail=get_error_detail(params.result.error)
                    if params.result.error
                    else "",
                    error_type=type(params.result.error).__name__ if params.result.error else "",
                    execution_time=params.duration,
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
                agents_completed=summary.get("completed", 0),
                agents_skipped=summary.get("skipped", 0),
                agents_failed=summary.get("failed", 0),
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
                failed_agent=get_manager().get_context("agent_name") or "",
            )
        )

        if self.services.support.manifest_manager:
            self.services.support.manifest_manager.mark_workflow_failed(get_error_detail(error))

        self.services.core.state_manager.mark_running_as_failed()

        # CLI decorator checks this attribute to prevent duplicate output
        error._already_displayed = True

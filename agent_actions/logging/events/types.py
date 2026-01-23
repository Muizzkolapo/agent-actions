"""
Agent-actions specific event type definitions.

This module defines all the event types used within agent-actions for
workflow orchestration, agent execution, LLM interactions, and validation.

Event Code Prefixes:
    W - Workflow lifecycle events
    A - Agent execution events
    B - Batch processing events
    L - LLM interaction events
    V - Validation events
"""

from dataclasses import dataclass, field
from typing import Any

from agent_actions.logging.core.events import BaseEvent, EventLevel


class EventCategories:
    """Event category constants for agent-actions."""

    WORKFLOW = "workflow"
    AGENT = "agent"
    BATCH = "batch"
    LLM = "llm"
    VALIDATION = "validation"


def _safe_value_repr(value: Any, max_length: int = 100) -> str:
    """Safely convert a value to a string representation for logging.

    Handles complex objects that may not serialize well to JSON by using repr()
    and truncating if necessary.

    Args:
        value: The value to convert
        max_length: Maximum length of the resulting string

    Returns:
        A string representation of the value, truncated if necessary
    """
    if value is None:
        return ""
    try:
        # Try simple str first for common types
        if isinstance(value, (str, int, float, bool)):
            result = str(value)
        else:
            result = repr(value)
        if len(result) > max_length:
            return result[: max_length - 3] + "..."
        return result
    except Exception:
        return "<unserializable>"


# =============================================================================
# Workflow Events (W prefix)
# =============================================================================


@dataclass
class WorkflowStartEvent(BaseEvent):
    """Fired when a workflow execution begins."""

    workflow_name: str = ""
    agent_count: int = 0
    execution_mode: str = "sequential"
    run_upstream: bool = False
    run_downstream: bool = False

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.WORKFLOW
        self.message = f"Running workflow {self.workflow_name} ({self.agent_count} agents)"
        self.data = {
            "workflow_name": self.workflow_name,
            "agent_count": self.agent_count,
            "execution_mode": self.execution_mode,
            "run_upstream": self.run_upstream,
            "run_downstream": self.run_downstream,
        }

    @property
    def code(self) -> str:
        return "W001"


@dataclass
class WorkflowCompleteEvent(BaseEvent):
    """Fired when a workflow execution completes successfully."""

    workflow_name: str = ""
    elapsed_time: float = 0.0
    agents_completed: int = 0
    agents_skipped: int = 0
    agents_failed: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.WORKFLOW
        self.message = (
            f"Completed workflow {self.workflow_name} in {self.elapsed_time:.2f}s | "
            f"{self.agents_completed} completed | {self.agents_skipped} skipped | "
            f"{self.agents_failed} failed"
        )
        self.data = {
            "workflow_name": self.workflow_name,
            "elapsed_time": self.elapsed_time,
            "agents_completed": self.agents_completed,
            "agents_skipped": self.agents_skipped,
            "agents_failed": self.agents_failed,
            "total_tokens": self.total_tokens,
        }

    @property
    def code(self) -> str:
        return "W002"


@dataclass
class WorkflowFailedEvent(BaseEvent):
    """Fired when a workflow execution fails."""

    workflow_name: str = ""
    error_message: str = ""
    error_type: str = ""
    elapsed_time: float = 0.0
    failed_agent: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.WORKFLOW
        self.message = f"Workflow {self.workflow_name} failed: {self.error_message}"
        self.data = {
            "workflow_name": self.workflow_name,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "elapsed_time": self.elapsed_time,
            "failed_agent": self.failed_agent,
        }

    @property
    def code(self) -> str:
        return "W003"


# =============================================================================
# Agent Events (A prefix)
# =============================================================================


@dataclass
class AgentStartEvent(BaseEvent):
    """Fired when an agent starts execution."""

    agent_name: str = ""
    agent_index: int = 0
    total_agents: int = 0
    agent_type: str = ""
    input_path: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.AGENT
        idx_str = f"{self.agent_index + 1}/{self.total_agents}"
        self.message = f"{idx_str} START {self.agent_name}"
        self.data = {
            "agent_name": self.agent_name,
            "agent_index": self.agent_index,
            "total_agents": self.total_agents,
            "agent_type": self.agent_type,
            "input_path": self.input_path,
        }

    @property
    def code(self) -> str:
        return "A001"


@dataclass
class AgentCompleteEvent(BaseEvent):
    """Fired when an agent completes successfully."""

    agent_name: str = ""
    agent_index: int = 0
    total_agents: int = 0
    execution_time: float = 0.0
    output_path: str = ""
    record_count: int = 0
    tokens: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.AGENT
        idx_str = f"{self.agent_index + 1}/{self.total_agents}"
        total_tokens = self.tokens.get("total_tokens", 0)
        self.message = (
            f"{idx_str} OK {self.agent_name} in {self.execution_time:.2f}s ({total_tokens} tokens)"
        )
        self.data = {
            "agent_name": self.agent_name,
            "agent_index": self.agent_index,
            "total_agents": self.total_agents,
            "execution_time": self.execution_time,
            "output_path": self.output_path,
            "record_count": self.record_count,
            "tokens": self.tokens,
        }

    @property
    def code(self) -> str:
        return "A002"


@dataclass
class AgentSkipEvent(BaseEvent):
    """Fired when an agent is skipped (e.g., already completed or cached)."""

    agent_name: str = ""
    agent_index: int = 0
    total_agents: int = 0
    skip_reason: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.AGENT
        idx_str = f"{self.agent_index + 1}/{self.total_agents}"
        self.message = f"{idx_str} SKIP {self.agent_name} ({self.skip_reason})"
        self.data = {
            "agent_name": self.agent_name,
            "agent_index": self.agent_index,
            "total_agents": self.total_agents,
            "skip_reason": self.skip_reason,
        }

    @property
    def code(self) -> str:
        return "A003"


@dataclass
class AgentFailedEvent(BaseEvent):
    """Fired when an agent fails execution."""

    agent_name: str = ""
    agent_index: int = 0
    total_agents: int = 0
    error_message: str = ""
    error_type: str = ""
    execution_time: float = 0.0
    suggestion: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.AGENT
        idx_str = f"{self.agent_index + 1}/{self.total_agents}"
        self.message = f"{idx_str} ERROR {self.agent_name}: {self.error_message}"
        self.data = {
            "agent_name": self.agent_name,
            "agent_index": self.agent_index,
            "total_agents": self.total_agents,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "execution_time": self.execution_time,
            "suggestion": self.suggestion,
        }

    @property
    def code(self) -> str:
        return "A004"


@dataclass
class AgentCachedEvent(BaseEvent):
    """Fired when an agent result is retrieved from cache."""

    agent_name: str = ""
    agent_index: int = 0
    total_agents: int = 0
    cache_key: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.AGENT
        idx_str = f"{self.agent_index + 1}/{self.total_agents}"
        self.message = f"{idx_str} CACHED {self.agent_name}"
        self.data = {
            "agent_name": self.agent_name,
            "agent_index": self.agent_index,
            "total_agents": self.total_agents,
            "cache_key": self.cache_key,
        }

    @property
    def code(self) -> str:
        return "A005"


# =============================================================================
# Batch Events (B prefix)
# =============================================================================


@dataclass
class BatchSubmittedEvent(BaseEvent):
    """Fired when a batch is submitted for processing."""

    batch_id: str = ""
    agent_name: str = ""
    request_count: int = 0
    provider: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        self.message = (
            f"Batch {self.batch_id} submitted: {self.request_count} requests to {self.provider}"
        )
        self.data = {
            "batch_id": self.batch_id,
            "agent_name": self.agent_name,
            "request_count": self.request_count,
            "provider": self.provider,
        }

    @property
    def code(self) -> str:
        return "B001"


@dataclass
class BatchProgressEvent(BaseEvent):
    """Fired to report batch processing progress."""

    batch_id: str = ""
    completed: int = 0
    total: int = 0
    failed: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.BATCH
        pct = (self.completed / self.total * 100) if self.total > 0 else 0
        self.message = f"Batch {self.batch_id}: {self.completed}/{self.total} ({pct:.1f}%)"
        self.data = {
            "batch_id": self.batch_id,
            "completed": self.completed,
            "total": self.total,
            "failed": self.failed,
            "percentage": pct,
        }

    @property
    def code(self) -> str:
        return "B002"


@dataclass
class BatchCompleteEvent(BaseEvent):
    """Fired when a batch completes processing."""

    batch_id: str = ""
    agent_name: str = ""
    total: int = 0
    completed: int = 0
    failed: int = 0
    elapsed_time: float = 0.0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        status = "OK" if self.failed == 0 else f"PARTIAL ({self.failed} failed)"
        self.message = f"Batch {self.batch_id} {status} in {self.elapsed_time:.2f}s"
        self.data = {
            "batch_id": self.batch_id,
            "agent_name": self.agent_name,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "elapsed_time": self.elapsed_time,
            "total_tokens": self.total_tokens,
        }

    @property
    def code(self) -> str:
        return "B003"


@dataclass
class BatchProcessingCompleteEvent(BaseEvent):
    """Fired when all batch jobs for an agent are completed."""

    agent_name: str = ""
    total_jobs: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        self.message = f"All batch jobs completed for {self.agent_name}"
        self.data = {
            "agent_name": self.agent_name,
            "total_jobs": self.total_jobs,
        }

    @property
    def code(self) -> str:
        return "B004"


@dataclass
class BatchResultsProcessedEvent(BaseEvent):
    """Fired when batch results have been processed."""

    agent_name: str = ""
    results_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        self.message = f"Processed all batch results for {self.agent_name}"
        self.data = {
            "agent_name": self.agent_name,
            "results_count": self.results_count,
        }

    @property
    def code(self) -> str:
        return "B005"


@dataclass
class BatchErrorEvent(BaseEvent):
    """Fired when a batch processing error occurs."""

    agent_name: str = ""
    error_message: str = ""
    error_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.BATCH
        self.message = f"Batch error for {self.agent_name}: {self.error_message}"
        self.data = {
            "agent_name": self.agent_name,
            "error_message": self.error_message,
            "error_type": self.error_type,
        }

    @property
    def code(self) -> str:
        return "B006"


@dataclass
class BatchPassthroughEvent(BaseEvent):
    """Fired when all items were filtered and passthrough data was processed."""

    agent_name: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        self.message = (
            f"All items filtered by conditional clause - passthrough data processed for {self.agent_name}"
        )
        self.data = {
            "agent_name": self.agent_name,
        }

    @property
    def code(self) -> str:
        return "B007"


@dataclass
class BatchStatusEvent(BaseEvent):
    """Fired to report batch status."""

    agent_name: str = ""
    status_message: str = ""
    status_type: str = "info"  # info, warning, error

    def __post_init__(self) -> None:
        level_map = {
            "info": EventLevel.INFO,
            "warning": EventLevel.WARN,
            "error": EventLevel.ERROR,
        }
        self.level = level_map.get(self.status_type, EventLevel.INFO)
        self.category = EventCategories.BATCH
        self.message = self.status_message or f"Batch status for {self.agent_name}"
        self.data = {
            "agent_name": self.agent_name,
            "status_message": self.status_message,
            "status_type": self.status_type,
        }

    @property
    def code(self) -> str:
        return "B008"


# =============================================================================
# LLM Events (L prefix)
# =============================================================================


@dataclass
class LLMRequestEvent(BaseEvent):
    """Fired when an LLM request is made."""

    provider: str = ""
    model: str = ""
    agent_name: str = ""
    prompt_tokens: int = 0
    request_id: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.LLM
        self.message = (
            f"LLM request to {self.provider}/{self.model} ({self.prompt_tokens} prompt tokens)"
        )
        self.data = {
            "provider": self.provider,
            "model": self.model,
            "agent_name": self.agent_name,
            "prompt_tokens": self.prompt_tokens,
            "request_id": self.request_id,
        }

    @property
    def code(self) -> str:
        return "L001"


@dataclass
class LLMResponseEvent(BaseEvent):
    """Fired when an LLM response is received."""

    provider: str = ""
    model: str = ""
    agent_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    request_id: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.LLM
        self.message = f"LLM response: {self.total_tokens} tokens in {self.latency_ms:.0f}ms"
        self.data = {
            "provider": self.provider,
            "model": self.model,
            "agent_name": self.agent_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
        }

    @property
    def code(self) -> str:
        return "L002"


@dataclass
class LLMErrorEvent(BaseEvent):
    """Fired when an LLM request fails."""

    provider: str = ""
    model: str = ""
    agent_name: str = ""
    error_message: str = ""
    error_type: str = ""
    retry_count: int = 0
    request_id: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.LLM
        self.message = f"LLM error ({self.provider}/{self.model}): {self.error_message}"
        self.data = {
            "provider": self.provider,
            "model": self.model,
            "agent_name": self.agent_name,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
            "request_id": self.request_id,
        }

    @property
    def code(self) -> str:
        return "L003"


@dataclass
class RateLimitEvent(BaseEvent):
    """Fired when a rate limit is hit."""

    provider: str = ""
    retry_after: float = 0.0
    agent_name: str = ""
    request_id: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.LLM
        self.message = f"Rate limit hit ({self.provider}), retrying in {self.retry_after:.1f}s"
        self.data = {
            "provider": self.provider,
            "retry_after": self.retry_after,
            "agent_name": self.agent_name,
            "request_id": self.request_id,
        }

    @property
    def code(self) -> str:
        return "L004"


# =============================================================================
# Validation Events (V prefix)
# =============================================================================


@dataclass
class ValidationStartEvent(BaseEvent):
    """Fired when validation begins."""

    target: str = ""
    validator: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.VALIDATION
        self.message = f"Validating {self.target} ({self.validator})"
        self.data = {
            "target": self.target,
            "validator": self.validator,
        }

    @property
    def code(self) -> str:
        return "V001"


@dataclass
class ValidationCompleteEvent(BaseEvent):
    """Fired when validation completes successfully."""

    target: str = ""
    validator: str = ""
    elapsed_time: float = 0.0
    warning_count: int = 0
    error_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG if self.error_count == 0 else EventLevel.ERROR
        self.category = EventCategories.VALIDATION
        status_parts = []
        if self.warning_count > 0:
            status_parts.append(f"{self.warning_count} warnings")
        if self.error_count > 0:
            status_parts.append(f"{self.error_count} errors")
        status_str = f" ({', '.join(status_parts)})" if status_parts else ""
        result = "passed" if self.error_count == 0 else "failed"
        self.message = f"Validation {result}: {self.target} in {self.elapsed_time:.2f}s{status_str}"
        self.data = {
            "target": self.target,
            "validator": self.validator,
            "elapsed_time": self.elapsed_time,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
        }

    @property
    def code(self) -> str:
        return "V002"


@dataclass
class ValidationErrorEvent(BaseEvent):
    """Fired when validation finds an error."""

    target: str = ""
    field: str = ""
    error: str = ""
    value: Any = None

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.VALIDATION
        location = f"{self.target}.{self.field}" if self.field else self.target
        value_repr = _safe_value_repr(self.value)
        value_str = f' (got: "{value_repr}")' if value_repr else ""
        self.message = f"VALIDATION ERROR in {location}: {self.error}{value_str}"
        self.data = {
            "target": self.target,
            "field": self.field,
            "error": self.error,
            "value": value_repr if value_repr else None,
        }

    @property
    def code(self) -> str:
        return "V003"


@dataclass
class ValidationWarningEvent(BaseEvent):
    """Fired when validation finds a warning (non-fatal issue)."""

    target: str = ""
    field: str = ""
    warning: str = ""
    value: Any = None

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.VALIDATION
        location = f"{self.target}.{self.field}" if self.field else self.target
        value_repr = _safe_value_repr(self.value)
        value_str = f" (value: {value_repr})" if value_repr else ""
        self.message = f"VALIDATION WARNING in {location}: {self.warning}{value_str}"
        self.data = {
            "target": self.target,
            "field": self.field,
            "warning": self.warning,
            "value": value_repr if value_repr else None,
        }

    @property
    def code(self) -> str:
        return "V004"

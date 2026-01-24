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
    C - Cache events
    T - Template rendering events
    D - Data loading/parsing events
    G - Guard evaluation events
    R - Recovery/retry events
    F - Configuration loading events
    E - Environment variable events
    I - Initialization/CLI events
    P - Plugin/UDF discovery events
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_actions.logging.core.events import BaseEvent, EventLevel


class EventCategories:
    """Event category constants for agent-actions."""

    WORKFLOW = "workflow"
    AGENT = "agent"
    BATCH = "batch"
    LLM = "llm"
    VALIDATION = "validation"
    CACHE = "cache"
    TEMPLATE = "template"
    DATA = "data"
    GUARD = "guard"
    RECOVERY = "recovery"
    CONFIGURATION = "configuration"
    ENVIRONMENT = "environment"
    INITIALIZATION = "initialization"
    PLUGIN = "plugin"


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
        self.message = f"All items filtered by conditional clause - passthrough data processed for {self.agent_name}"
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


# =============================================================================
# Cache Events (C prefix)
# =============================================================================


@dataclass
class CacheHitEvent(BaseEvent):
    """Fired when a cache hit occurs."""

    cache_type: str = ""
    key: str = ""
    hit_rate: Optional[float] = None

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        hit_rate_str = f" (hit rate: {self.hit_rate:.1%})" if self.hit_rate is not None else ""
        self.message = f"Cache hit: {self.cache_type}[{self.key}]{hit_rate_str}"
        self.data = {
            "cache_type": self.cache_type,
            "key": self.key,
            "hit_rate": self.hit_rate,
        }

    @property
    def code(self) -> str:
        return "C001"


@dataclass
class CacheMissEvent(BaseEvent):
    """Fired when a cache miss occurs."""

    cache_type: str = ""
    key: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        reason_str = f" ({self.reason})" if self.reason else ""
        self.message = f"Cache miss: {self.cache_type}[{self.key}]{reason_str}"
        self.data = {
            "cache_type": self.cache_type,
            "key": self.key,
            "reason": self.reason,
        }

    @property
    def code(self) -> str:
        return "C002"


@dataclass
class CacheInvalidationEvent(BaseEvent):
    """Fired when cache is invalidated."""

    cache_type: str = ""
    entries_removed: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.CACHE
        reason_str = f" - {self.reason}" if self.reason else ""
        self.message = (
            f"Cache invalidated: {self.cache_type} ({self.entries_removed} entries){reason_str}"
        )
        self.data = {
            "cache_type": self.cache_type,
            "entries_removed": self.entries_removed,
            "reason": self.reason,
        }

    @property
    def code(self) -> str:
        return "C003"


@dataclass
class CacheLoadEvent(BaseEvent):
    """Fired when cache is loaded."""

    cache_type: str = ""
    entries_loaded: int = 0
    source: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        self.message = (
            f"Cache loaded: {self.cache_type} ({self.entries_loaded} entries from {self.source})"
        )
        self.data = {
            "cache_type": self.cache_type,
            "entries_loaded": self.entries_loaded,
            "source": self.source,
        }

    @property
    def code(self) -> str:
        return "C004"


@dataclass
class CacheUpdateEvent(BaseEvent):
    """Fired when cache is updated."""

    cache_type: str = ""
    key: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        self.message = f"Cache updated: {self.cache_type}[{self.key}]"
        self.data = {
            "cache_type": self.cache_type,
            "key": self.key,
        }

    @property
    def code(self) -> str:
        return "C005"


@dataclass
class CacheStatsEvent(BaseEvent):
    """Fired to report cache statistics."""

    cache_type: str = ""
    hit_count: int = 0
    miss_count: int = 0
    total_entries: int = 0
    size_bytes: Optional[int] = None

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CACHE
        total_accesses = self.hit_count + self.miss_count
        hit_rate = self.hit_count / total_accesses if total_accesses > 0 else 0.0
        size_str = f" | {self.size_bytes:,} bytes" if self.size_bytes is not None else ""
        self.message = (
            f"Cache stats: {self.cache_type} - {hit_rate:.1%} hit rate "
            f"({self.hit_count} hits, {self.miss_count} misses, {self.total_entries} entries{size_str})"
        )
        self.data = {
            "cache_type": self.cache_type,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "total_entries": self.total_entries,
            "size_bytes": self.size_bytes,
            "hit_rate": hit_rate,
        }

    @property
    def code(self) -> str:
        return "C006"


# =============================================================================
# Template Rendering Events (T prefix)
# =============================================================================


@dataclass
class TemplateRenderingFailedEvent(BaseEvent):
    """Fired when template rendering fails due to undefined variables."""

    agent_name: str = ""
    missing_variables: List[str] = field(default_factory=list)
    error_message: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.TEMPLATE
        vars_str = ", ".join(self.missing_variables) if self.missing_variables else "unknown"
        self.message = (
            f"Template for '{self.agent_name}' references undefined variables: {vars_str}"
        )
        self.data = {
            "agent_name": self.agent_name,
            "missing_variables": self.missing_variables,
            "error_message": self.error_message,
        }

    @property
    def code(self) -> str:
        return "T001"


@dataclass
class TemplateSyntaxErrorEvent(BaseEvent):
    """Fired when template has syntax errors."""

    agent_name: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.TEMPLATE
        self.message = f"Template syntax error in '{self.agent_name}': {self.error}"
        self.data = {
            "agent_name": self.agent_name,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "T002"


# =============================================================================
# LLM Error Events (L prefix - L005 onwards, L001-L004 are normal LLM events)
# =============================================================================


@dataclass
class LLMJSONParseErrorEvent(BaseEvent):
    """Fired when LLM returns unparseable JSON."""

    provider: str = ""
    model: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.LLM
        self.message = f"{self.provider}/{self.model} returned invalid JSON: {self.error}"
        self.data = {
            "provider": self.provider,
            "model": self.model,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "L005"


@dataclass
class LLMConnectionErrorEvent(BaseEvent):
    """Fired when LLM connection/timeout error occurs."""

    provider: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.LLM
        self.message = f"{self.provider} connection error: {self.error}"
        self.data = {
            "provider": self.provider,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "L006"


@dataclass
class LLMServerErrorEvent(BaseEvent):
    """Fired when LLM server error (5xx) occurs."""

    provider: str = ""
    status_code: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.LLM
        self.message = f"{self.provider} server error ({self.status_code}): {self.error}"
        self.data = {
            "provider": self.provider,
            "status_code": self.status_code,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "L007"


# =============================================================================
# Batch Error Events (B prefix - B004 onwards, B001-B003 are normal batch events)
# =============================================================================


@dataclass
class BatchSubmissionFailedEvent(BaseEvent):
    """Fired when batch submission fails."""

    batch_id: str = ""
    provider: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.BATCH
        self.message = f"Batch submission failed ({self.provider}): {self.error}"
        self.data = {
            "batch_id": self.batch_id,
            "provider": self.provider,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "B004"


@dataclass
class BatchStatusCheckFailedEvent(BaseEvent):
    """Fired when batch status check fails."""

    batch_id: str = ""
    provider: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.BATCH
        self.message = f"Failed to check batch status for {self.batch_id}: {self.error}"
        self.data = {
            "batch_id": self.batch_id,
            "provider": self.provider,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "B005"


@dataclass
class BatchResultProcessingFailedEvent(BaseEvent):
    """Fired when batch result processing fails."""

    batch_id: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.BATCH
        self.message = f"Failed to process batch results for {self.batch_id}: {self.error}"
        self.data = {
            "batch_id": self.batch_id,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "B006"


@dataclass
class BatchPartialFailureEvent(BaseEvent):
    """Fired when some batch items fail."""

    batch_id: str = ""
    failed_count: int = 0
    total_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.BATCH
        self.message = f"Batch {self.batch_id} partial failure: {self.failed_count}/{self.total_count} items failed"
        self.data = {
            "batch_id": self.batch_id,
            "failed_count": self.failed_count,
            "total_count": self.total_count,
        }

    @property
    def code(self) -> str:
        return "B007"


# =============================================================================
# Data Loading/Parsing Events (D prefix)
# =============================================================================


@dataclass
class DataParsingErrorEvent(BaseEvent):
    """Fired when data parsing fails."""

    file_path: str = ""
    format: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.DATA
        self.message = f"Failed to parse {self.format} from {self.file_path}: {self.error}"
        self.data = {
            "file_path": self.file_path,
            "format": self.format,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "D001"


@dataclass
class DataLoadingErrorEvent(BaseEvent):
    """Fired when data loading fails."""

    file_path: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.DATA
        self.message = f"Failed to load data from {self.file_path}: {self.error}"
        self.data = {
            "file_path": self.file_path,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "D002"


@dataclass
class DataValidationErrorEvent(BaseEvent):
    """Fired when data validation fails."""

    file_path: str = ""
    validation_error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.DATA
        self.message = f"Data validation failed for {self.file_path}: {self.validation_error}"
        self.data = {
            "file_path": self.file_path,
            "validation_error": self.validation_error,
        }

    @property
    def code(self) -> str:
        return "D003"


# =============================================================================
# Guard Evaluation Events (G prefix)
# =============================================================================


@dataclass
class GuardEvaluationTimeoutEvent(BaseEvent):
    """Fired when guard evaluation times out."""

    guard_clause: str = ""
    timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.GUARD
        self.message = (
            f"Guard evaluation timed out after {self.timeout_seconds}s: {self.guard_clause}"
        )
        self.data = {
            "guard_clause": self.guard_clause,
            "timeout_seconds": self.timeout_seconds,
        }

    @property
    def code(self) -> str:
        return "G001"


@dataclass
class GuardEvaluationErrorEvent(BaseEvent):
    """Fired when guard evaluation fails with error."""

    guard_clause: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.GUARD
        self.message = f"Guard evaluation failed: {self.error}"
        self.data = {
            "guard_clause": self.guard_clause,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "G002"


# =============================================================================
# Recovery/Retry Events (R prefix)
# =============================================================================


@dataclass
class RetryExhaustedEvent(BaseEvent):
    """Fired when retries are exhausted."""

    attempt: int = 0
    max_attempts: int = 0
    reason: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.RECOVERY
        self.message = (
            f"Retry exhausted after {self.attempt}/{self.max_attempts} attempts: {self.reason}"
        )
        self.data = {
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "reason": self.reason,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "R001"


@dataclass
class RepromptValidationFailedEvent(BaseEvent):
    """Fired when reprompt validation fails."""

    agent_name: str = ""
    attempt: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.RECOVERY
        self.message = f"Reprompt validation failed for '{self.agent_name}' (attempt {self.attempt}): {self.error}"
        self.data = {
            "agent_name": self.agent_name,
            "attempt": self.attempt,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "R002"


@dataclass
class RecoveryErrorEvent(BaseEvent):
    """Fired when recovery mechanism itself fails."""

    recovery_type: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.RECOVERY
        self.message = f"Recovery mechanism failed ({self.recovery_type}): {self.error}"
        self.data = {
            "recovery_type": self.recovery_type,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "R003"


# =============================================================================
# Configuration Events (F prefix - F for conFiguration, C is taken by Cache)
# =============================================================================


@dataclass
class ConfigLoadStartEvent(BaseEvent):
    """Fired when configuration loading starts."""

    config_file: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CONFIGURATION
        self.message = f"Loading config from {self.config_file}"
        self.data = {
            "config_file": self.config_file,
        }

    @property
    def code(self) -> str:
        return "F001"


@dataclass
class ConfigLoadEvent(BaseEvent):
    """Fired when configuration is loaded successfully."""

    config_file: str = ""
    config_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.CONFIGURATION
        self.message = f"Loaded {self.config_type} config from {self.config_file}"
        self.data = {
            "config_file": self.config_file,
            "config_type": self.config_type,
        }

    @property
    def code(self) -> str:
        return "F002"


@dataclass
class ConfigLoadCompleteEvent(BaseEvent):
    """Fired when all configurations are loaded.

    NOTE: This event is defined but not yet instrumented. Reserved for future use.
    See TICKET-019 for instrumentation plan.
    """

    config_count: int = 0
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.CONFIGURATION
        self.message = (
            f"All configurations loaded ({self.config_count} files) in {self.elapsed_time:.2f}s"
        )
        self.data = {
            "config_count": self.config_count,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "F003"


@dataclass
class ConfigValidationEvent(BaseEvent):
    """Fired when configuration validation occurs.

    NOTE: This event is defined but not yet instrumented. Reserved for future use.
    See TICKET-019 for instrumentation plan.
    """

    validation_target: str = ""
    result: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CONFIGURATION
        self.message = f"Config validation for {self.validation_target}: {self.result}"
        self.data = {
            "validation_target": self.validation_target,
            "result": self.result,
        }

    @property
    def code(self) -> str:
        return "F004"


# =============================================================================
# Environment Variable Events (E prefix)
# NOTE: These events are defined but not yet instrumented (deferred as LOW priority).
#       Environment variables are already visible via configuration logging.
#       See TICKET-019 for details.
# =============================================================================


@dataclass
class EnvironmentLoadStartEvent(BaseEvent):
    """Fired when environment variable loading starts."""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.ENVIRONMENT
        self.message = "Loading environment variables"
        self.data = {}

    @property
    def code(self) -> str:
        return "E001"


@dataclass
class EnvironmentVariableDetectedEvent(BaseEvent):
    """Fired when an environment variable is detected."""

    var_name: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.ENVIRONMENT
        self.message = f"Environment variable detected: {self.var_name}"
        self.data = {
            "var_name": self.var_name,
        }

    @property
    def code(self) -> str:
        return "E002"


@dataclass
class EnvironmentLoadCompleteEvent(BaseEvent):
    """Fired when environment variable loading completes."""

    var_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.ENVIRONMENT
        self.message = f"Environment loaded ({self.var_count} variables)"
        self.data = {
            "var_count": self.var_count,
        }

    @property
    def code(self) -> str:
        return "E003"


# =============================================================================
# Initialization Events (I prefix - CLI, System, Project)
# =============================================================================


@dataclass
class CLIInitStartEvent(BaseEvent):
    """Fired when CLI initialization starts."""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = "CLI initialization started"
        self.data = {}

    @property
    def code(self) -> str:
        return "I001"


@dataclass
class CLIArgumentParsingEvent(BaseEvent):
    """Fired before CLI arguments are parsed.

    Contains raw argv before Click processes the arguments. The args field
    contains the raw command-line arguments, not the parsed result.
    """

    command: str = ""
    args: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = f"CLI invoked with command: {self.command}"
        self.data = {
            "command": self.command,
            "args": self.args,
        }

    @property
    def code(self) -> str:
        return "I002"


@dataclass
class CLIInitCompleteEvent(BaseEvent):
    """Fired when CLI initialization completes."""

    command: str = ""
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = (
            f"CLI initialization complete for '{self.command}' in {self.elapsed_time:.2f}s"
        )
        self.data = {
            "command": self.command,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "I003"


@dataclass
class ApplicationInitializationStartEvent(BaseEvent):
    """Fired when application initialization starts."""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.INITIALIZATION
        self.message = "Application initialization started"
        self.data = {}

    @property
    def code(self) -> str:
        return "I004"


@dataclass
class StartupValidationStartEvent(BaseEvent):
    """Fired when startup validation starts."""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = "Startup validation started"
        self.data = {}

    @property
    def code(self) -> str:
        return "I005"


@dataclass
class StartupValidationCompleteEvent(BaseEvent):
    """Fired when startup validation completes."""

    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.INITIALIZATION
        self.message = f"Startup validation complete in {self.elapsed_time:.2f}s"
        self.data = {
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "I006"


@dataclass
class DIContainerInitializationEvent(BaseEvent):
    """Fired when DI container is initialized."""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = "DI container initialized"
        self.data = {}

    @property
    def code(self) -> str:
        return "I007"


@dataclass
class WorkflowInitializationStartEvent(BaseEvent):
    """Fired when workflow initialization starts."""

    workflow_name: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = f"Workflow initialization started: {self.workflow_name}"
        self.data = {
            "workflow_name": self.workflow_name,
        }

    @property
    def code(self) -> str:
        return "I008"


@dataclass
class WorkflowServicesInitializationStartEvent(BaseEvent):
    """Fired when workflow services initialization starts."""

    workflow_name: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = f"Workflow services initialization started: {self.workflow_name}"
        self.data = {
            "workflow_name": self.workflow_name,
        }

    @property
    def code(self) -> str:
        return "I009"


@dataclass
class ProjectInitializationStartEvent(BaseEvent):
    """Fired when project initialization starts."""

    project_path: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.INITIALIZATION
        self.message = f"Project initialization started: {self.project_path}"
        self.data = {
            "project_path": self.project_path,
        }

    @property
    def code(self) -> str:
        return "I010"


@dataclass
class ProjectValidationEvent(BaseEvent):
    """Fired during project validation."""

    validation_target: str = ""
    result: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = f"Project validation ({self.validation_target}): {self.result}"
        self.data = {
            "validation_target": self.validation_target,
            "result": self.result,
        }

    @property
    def code(self) -> str:
        return "I011"


@dataclass
class ProjectDirectoryCreatedEvent(BaseEvent):
    """Fired when project directory is created."""

    directory_path: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.INITIALIZATION
        self.message = f"Project directory created: {self.directory_path}"
        self.data = {
            "directory_path": self.directory_path,
        }

    @property
    def code(self) -> str:
        return "I012"


@dataclass
class ProjectInitializedEvent(BaseEvent):
    """Fired when project initialization completes."""

    project_path: str = ""
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.INITIALIZATION
        self.message = f"Project initialized: {self.project_path} in {self.elapsed_time:.2f}s"
        self.data = {
            "project_path": self.project_path,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "I013"


# =============================================================================
# Plugin/UDF Events (P prefix)
# =============================================================================


@dataclass
class UDFDiscoveryStartEvent(BaseEvent):
    """Fired when UDF discovery starts."""

    search_path: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.PLUGIN
        self.message = f"Discovering UDFs in {self.search_path}"
        self.data = {
            "search_path": self.search_path,
        }

    @property
    def code(self) -> str:
        return "P001"


@dataclass
class UDFDiscoveredEvent(BaseEvent):
    """Fired when a UDF is discovered."""

    udf_name: str = ""
    udf_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.PLUGIN
        self.message = f"Discovered UDF: {self.udf_name} ({self.udf_type})"
        self.data = {
            "udf_name": self.udf_name,
            "udf_type": self.udf_type,
        }

    @property
    def code(self) -> str:
        return "P002"


@dataclass
class UDFDiscoveryCompleteEvent(BaseEvent):
    """Fired when UDF discovery completes."""

    total_udfs: int = 0
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.PLUGIN
        self.message = (
            f"UDF discovery complete: {self.total_udfs} UDFs found in {self.elapsed_time:.2f}s"
        )
        self.data = {
            "total_udfs": self.total_udfs,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "P003"


@dataclass
class ProcessorRegistrationEvent(BaseEvent):
    """Fired when a processor is registered."""

    processor_name: str = ""
    processor_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.PLUGIN
        self.message = f"Processor registered: {self.processor_name} ({self.processor_type})"
        self.data = {
            "processor_name": self.processor_name,
            "processor_type": self.processor_type,
        }

    @property
    def code(self) -> str:
        return "P004"

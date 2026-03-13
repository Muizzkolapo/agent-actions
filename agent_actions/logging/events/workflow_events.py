"""Workflow and agent lifecycle events (W/A prefixes)."""

from dataclasses import dataclass, field

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories

__all__ = [
    "WorkflowStartEvent",
    "WorkflowCompleteEvent",
    "WorkflowFailedEvent",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentSkipEvent",
    "AgentFailedEvent",
    "AgentCachedEvent",
]


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
    error_detail: str = ""
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
            "error_detail": self.error_detail or self.error_message,
            "error_type": self.error_type,
            "elapsed_time": self.elapsed_time,
            "failed_agent": self.failed_agent,
        }

    @property
    def code(self) -> str:
        return "W003"


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
    error_detail: str = ""
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
            "error_detail": self.error_detail or self.error_message,
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

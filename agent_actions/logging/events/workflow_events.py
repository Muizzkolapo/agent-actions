"""Workflow and action lifecycle events (W/A prefixes)."""

from dataclasses import dataclass, field

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories

__all__ = [
    "WorkflowStartEvent",
    "WorkflowCompleteEvent",
    "WorkflowFailedEvent",
    "ActionStartEvent",
    "ActionCompleteEvent",
    "ActionSkipEvent",
    "ActionFailedEvent",
    "ActionCachedEvent",
    "StepStartEvent",
    "StepCompleteEvent",
]


@dataclass
class WorkflowStartEvent(BaseEvent):
    """Fired when a workflow execution begins."""

    workflow_name: str = ""
    action_count: int = 0
    execution_mode: str = "sequential"

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.WORKFLOW
        noun = "action" if self.action_count == 1 else "actions"
        self.message = f"Running workflow {self.workflow_name} ({self.action_count} {noun})"
        self.data = {
            "workflow_name": self.workflow_name,
            "action_count": self.action_count,
            "execution_mode": self.execution_mode,
        }

    @property
    def code(self) -> str:
        return "W001"


@dataclass
class WorkflowCompleteEvent(BaseEvent):
    """Fired when a workflow execution completes successfully."""

    workflow_name: str = ""
    elapsed_time: float = 0.0
    actions_completed: int = 0
    actions_partial: int = 0
    actions_skipped: int = 0
    actions_failed: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.WORKFLOW
        self.message = (
            f"Completed workflow {self.workflow_name} in {self.elapsed_time:.2f}s | "
            f"{self.actions_completed} completed | {self.actions_partial} partial | "
            f"{self.actions_skipped} skipped | {self.actions_failed} failed"
        )
        self.data = {
            "workflow_name": self.workflow_name,
            "elapsed_time": self.elapsed_time,
            "actions_completed": self.actions_completed,
            "actions_partial": self.actions_partial,
            "actions_skipped": self.actions_skipped,
            "actions_failed": self.actions_failed,
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
    failed_action: str = ""

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
            "failed_action": self.failed_action,
        }

    @property
    def code(self) -> str:
        return "W003"


@dataclass
class ActionStartEvent(BaseEvent):
    """Fired when an action starts execution."""

    action_name: str = ""
    action_index: int = 0
    total_actions: int = 0
    action_type: str = ""
    input_path: str = ""
    mode: str = ""  # "online" or "batch" — see RunMode

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.ACTION
        idx_str = f"{self.action_index + 1}/{self.total_actions}"
        self.message = f"{idx_str} START {self.action_name}"
        self.data = {
            "action_name": self.action_name,
            "action_index": self.action_index,
            "total_actions": self.total_actions,
            "action_type": self.action_type,
            "input_path": self.input_path,
            "mode": self.mode,
        }

    @property
    def code(self) -> str:
        return "A001"


@dataclass
class ActionCompleteEvent(BaseEvent):
    """Fired when an action completes successfully."""

    action_name: str = ""
    action_index: int = 0
    total_actions: int = 0
    execution_time: float = 0.0
    output_path: str = ""
    record_count: int = 0
    tokens: dict[str, int] = field(default_factory=dict)
    mode: str = ""  # "online" or "batch" — see RunMode
    model_vendor: str = ""
    model_name: str = ""
    kind: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.ACTION
        idx_str = f"{self.action_index + 1}/{self.total_actions}"
        total_tokens = self.tokens.get("total_tokens", 0)
        self.message = (
            f"{idx_str} OK {self.action_name} in {self.execution_time:.2f}s ({total_tokens} tokens)"
        )
        self.data = {
            "action_name": self.action_name,
            "action_index": self.action_index,
            "total_actions": self.total_actions,
            "execution_time": self.execution_time,
            "output_path": self.output_path,
            "record_count": self.record_count,
            "tokens": self.tokens,
            "mode": self.mode,
            "model_vendor": self.model_vendor,
            "model_name": self.model_name,
            "kind": self.kind,
        }

    @property
    def code(self) -> str:
        return "A002"


@dataclass
class ActionSkipEvent(BaseEvent):
    """Fired when an action is skipped (e.g., already completed or cached)."""

    action_name: str = ""
    action_index: int = 0
    total_actions: int = 0
    skip_reason: str = ""
    mode: str = ""  # "online" or "batch" — see RunMode

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.ACTION
        idx_str = f"{self.action_index + 1}/{self.total_actions}"
        self.message = f"{idx_str} SKIP {self.action_name} ({self.skip_reason})"
        self.data = {
            "action_name": self.action_name,
            "action_index": self.action_index,
            "total_actions": self.total_actions,
            "skip_reason": self.skip_reason,
            "mode": self.mode,
        }

    @property
    def code(self) -> str:
        return "A003"


@dataclass
class ActionFailedEvent(BaseEvent):
    """Fired when an action fails execution."""

    action_name: str = ""
    action_index: int = 0
    total_actions: int = 0
    error_message: str = ""
    error_detail: str = ""
    error_type: str = ""
    execution_time: float = 0.0
    suggestion: str = ""
    mode: str = ""  # "online" or "batch" — see RunMode

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.ACTION
        idx_str = f"{self.action_index + 1}/{self.total_actions}"
        self.message = f"{idx_str} ERROR {self.action_name}: {self.error_message}"
        self.data = {
            "action_name": self.action_name,
            "action_index": self.action_index,
            "total_actions": self.total_actions,
            "error_message": self.error_message,
            "error_detail": self.error_detail or self.error_message,
            "error_type": self.error_type,
            "execution_time": self.execution_time,
            "suggestion": self.suggestion,
            "mode": self.mode,
        }

    @property
    def code(self) -> str:
        return "A004"


@dataclass
class ActionCachedEvent(BaseEvent):
    """Fired when an action result is retrieved from cache."""

    action_name: str = ""
    action_index: int = 0
    total_actions: int = 0
    cache_key: str = ""
    mode: str = ""  # "online" or "batch" — see RunMode

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.ACTION
        idx_str = f"{self.action_index + 1}/{self.total_actions}"
        self.message = f"{idx_str} CACHED {self.action_name}"
        self.data = {
            "action_name": self.action_name,
            "action_index": self.action_index,
            "total_actions": self.total_actions,
            "cache_key": self.cache_key,
            "mode": self.mode,
        }

    @property
    def code(self) -> str:
        return "A005"


@dataclass
class StepStartEvent(BaseEvent):
    """Fired when a dependency level begins executing."""

    step_index: int = 0
    total_steps: int = 0
    actions: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.WORKFLOW
        # 1-based: a run whose last line reads "Step 11/12" looks unfinished.
        idx_str = f"Step {self.step_index + 1}/{self.total_steps}"
        if not self.pending:
            self.message = f"{idx_str}: all actions already complete"
        elif len(self.pending) > 1:
            # Not "in parallel": the same level runs serially under
            # --execution-mode sequential.
            self.message = f"{idx_str}: {len(self.pending)} actions ({', '.join(self.pending)})"
        else:
            self.message = f"{idx_str}: {self.pending[0]}"
        self.data = {
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "actions": list(self.actions),
            "pending": list(self.pending),
        }

    @property
    def code(self) -> str:
        return "W004"


@dataclass
class StepCompleteEvent(BaseEvent):
    """Fired when a dependency level finishes, whatever the outcome."""

    step_index: int = 0
    total_steps: int = 0
    elapsed_time: float = 0.0
    completed: int = 0
    partial: int = 0
    skipped: int = 0
    failed: int = 0
    unfinished: int = 0
    batch_pending: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Always INFO: a step is a boundary, not a fault. ActionFailedEvent
        # reports failures, and a WARN here would double-count them wherever
        # warnings are collected.
        self.level = EventLevel.INFO
        self.category = EventCategories.WORKFLOW
        idx_str = f"Step {self.step_index + 1}/{self.total_steps}"
        if self.batch_pending:
            self.message = (
                f"{idx_str} paused after {self.elapsed_time:.2f}s — "
                f"{len(self.batch_pending)} batch job(s) pending"
            )
        elif self.unfinished:
            # Saying "complete" while actions are still mid-flight is the one
            # claim this event must never make.
            self.message = (
                f"{idx_str} ended after {self.elapsed_time:.2f}s — {self.unfinished} unfinished"
            )
        else:
            self.message = f"{idx_str} complete in {self.elapsed_time:.2f}s"
            if self.failed:
                self.message += f" ({self.failed} failed)"
        self.data = {
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "elapsed_time": self.elapsed_time,
            "completed": self.completed,
            "partial": self.partial,
            "skipped": self.skipped,
            "failed": self.failed,
            "unfinished": self.unfinished,
            "batch_pending": list(self.batch_pending),
        }

    @property
    def code(self) -> str:
        return "W005"

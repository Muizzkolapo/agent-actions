"""Unified task preparation data structures for batch and online modes."""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, cast

from agent_actions.config.types import RunMode

if TYPE_CHECKING:
    from agent_actions.processing.types import ProcessingContext
    from agent_actions.storage.backend import StorageBackend


class GuardStatus(Enum):
    """Result of guard evaluation during task preparation."""

    PASSED = "passed"  # Guard passed, task should be executed
    SKIPPED = "skipped"  # Guard triggered skip behavior (passthrough)
    FILTERED = "filtered"  # Guard triggered filter behavior (excluded)
    UPSTREAM_UNPROCESSED = "upstream_unprocessed"  # Upstream failed/skipped this record


@dataclass
class PreparedTask:
    """Task configuration ready for execution (online) or submission (batch)."""

    target_id: str
    source_guid: str | None
    formatted_prompt: str = ""
    llm_context: dict[str, Any] = field(default_factory=dict)

    passthrough_fields: dict[str, Any] = field(default_factory=dict)
    original_content: Any = None
    source_content: Any | None = None
    source_snapshot: Any | None = None
    guard_status: GuardStatus = GuardStatus.PASSED
    guard_behavior: str | None = None
    prompt_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def should_execute(self) -> bool:
        """Return True if guard passed and task should be executed."""
        return self.guard_status == GuardStatus.PASSED

    @property
    def is_passthrough(self) -> bool:
        """Return True if guard triggered skip (passthrough original content)."""
        return self.guard_status == GuardStatus.SKIPPED

    @property
    def is_filtered(self) -> bool:
        """Return True if guard triggered filter (exclude from output)."""
        return self.guard_status == GuardStatus.FILTERED

    @property
    def is_upstream_unprocessed(self) -> bool:
        """Return True if upstream failed/skipped this record."""
        return self.guard_status == GuardStatus.UPSTREAM_UNPROCESSED


@dataclass
class PreparationContext:
    """Context needed for task preparation, convertible from ProcessingContext."""

    agent_config: dict[str, Any]
    agent_name: str
    is_first_stage: bool = False
    mode: RunMode = RunMode.ONLINE
    source_data: list[dict[str, Any]] | None = None
    agent_indices: dict[str, int] | None = None
    dependency_configs: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] | None = None
    version_context: dict[str, Any] | None = None
    file_path: str | None = None
    output_directory: str | None = None
    tools_path: str | None = None
    storage_backend: Optional["StorageBackend"] = None
    current_item: dict[str, Any] | None = None
    record_index: int = 0

    @classmethod
    def from_processing_context(cls, context: "ProcessingContext") -> "PreparationContext":
        """Create PreparationContext from a ProcessingContext."""
        from agent_actions.utils.tools_resolver import resolve_tools_path

        return cls(
            agent_config=cast(dict[str, Any], context.agent_config),
            agent_name=context.agent_name,
            is_first_stage=context.is_first_stage,
            mode=context.mode,
            source_data=context.source_data,
            agent_indices=context.agent_indices,
            dependency_configs=context.dependency_configs,
            workflow_metadata=context.workflow_metadata,
            version_context=context.version_context,
            file_path=context.file_path,
            output_directory=context.output_directory,
            tools_path=resolve_tools_path(cast(dict[str, Any], context.agent_config)),
            storage_backend=context.storage_backend,
            current_item=context.current_item,
            record_index=context.record_index,
        )

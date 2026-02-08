"""
Unified task preparation data structures.

Part of Phase 2 (#890): Extract Shared PreparedTask Builder.

These dataclasses ensure identical task preparation for both batch and online modes.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


class GuardStatus(Enum):
    """Result of guard evaluation during task preparation."""

    PASSED = "passed"  # Guard passed, task should be executed
    SKIPPED = "skipped"  # Guard triggered skip behavior (passthrough)
    FILTERED = "filtered"  # Guard triggered filter behavior (excluded)
    UPSTREAM_UNPROCESSED = "upstream_unprocessed"  # Upstream failed/skipped this record


@dataclass
class PreparedTask:
    """
    Immutable task ready for execution (online) or submission (batch).

    This is the unified output of TaskPreparer.prepare() that both
    RecordProcessor and BatchTaskPreparator consume.

    Attributes:
        target_id: Unique identifier for this task (batch: custom_id)
        source_guid: Deterministic ID for lineage chaining across stages
        formatted_prompt: Fully rendered prompt ready for LLM
        llm_context: Context dict passed to LLM (with context_scope.drop applied)
        passthrough_fields: Fields to merge into output (from context_scope.passthrough)
        original_content: The original input content (for passthrough on skip)
        source_content: Resolved source content (for {{ source.* }} templates)
        source_snapshot: Snapshot of original item (for first-stage source saving)
        guard_status: Result of guard evaluation (PASSED/SKIPPED/FILTERED)
        guard_behavior: Specific behavior if guard blocked ('skip' or 'filter')
        prompt_context: Full context used in template rendering (for guard evaluation)
        metadata: Additional metadata dict
    """

    # Identity
    target_id: str
    source_guid: Optional[str]  # None for subsequent-stage items without source_guid

    # Prompt data (empty if guard blocked before prompt preparation)
    formatted_prompt: str = ""
    llm_context: Dict[str, Any] = field(default_factory=dict)

    # Context preservation
    passthrough_fields: Dict[str, Any] = field(default_factory=dict)
    original_content: Any = None
    source_content: Optional[Any] = None
    source_snapshot: Optional[Any] = None

    # Guard evaluation result
    guard_status: GuardStatus = GuardStatus.PASSED
    guard_behavior: Optional[str] = None  # 'skip' or 'filter' if not PASSED

    # Full context used for guard evaluation (includes rendered template variables)
    prompt_context: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def should_execute(self) -> bool:
        """Whether this task should be executed (guard passed)."""
        return self.guard_status == GuardStatus.PASSED

    @property
    def is_passthrough(self) -> bool:
        """Whether this task should pass through original content (guard skip)."""
        return self.guard_status == GuardStatus.SKIPPED

    @property
    def is_filtered(self) -> bool:
        """Whether this task was filtered out (guard filter)."""
        return self.guard_status == GuardStatus.FILTERED

    @property
    def is_upstream_unprocessed(self) -> bool:
        """Whether this task was unprocessed by upstream (dead/failed/skipped)."""
        return self.guard_status == GuardStatus.UPSTREAM_UNPROCESSED


@dataclass
class PreparationContext:
    """
    Context needed for task preparation.

    This mirrors ProcessingContext but is focused on preparation-only concerns.
    It can be constructed from a ProcessingContext or directly.

    Attributes:
        agent_config: Agent configuration dict
        agent_name: Agent name for metadata and logging
        is_first_stage: True for first-stage (raw input), False for subsequent-stage
        source_data: List of source items for source_guid lookups
        agent_indices: Dict mapping agent names to node indices (for historical data)
        dependency_configs: Dict mapping dependency names to configs
        workflow_metadata: Workflow-level metadata for {{ workflow.* }} templates
        version_context: Version context for {{ version.* }} templates (online mode)
        file_path: File path for history tracking
        output_directory: Output directory path
        tools_path: Path to tools directory
        storage_backend: Optional storage backend for historical data loading
        current_item: Current item dict (for lineage in subsequent-stage)
        record_index: Current record index (for logging/events)
    """

    # Core configuration
    agent_config: Dict[str, Any]
    agent_name: str

    # Stage indicator
    is_first_stage: bool = False

    # Mode indicator - True for batch processing, False for online/realtime
    is_batch_mode: bool = False

    # Source data for lookups
    source_data: Optional[List[Dict[str, Any]]] = None

    # Workflow context (for historical data loading)
    agent_indices: Optional[Dict[str, int]] = None
    dependency_configs: Optional[Dict[str, Any]] = None
    workflow_metadata: Optional[Dict[str, Any]] = None

    # Version context (online mode)
    version_context: Optional[Dict[str, Any]] = None

    # File context
    file_path: Optional[str] = None
    output_directory: Optional[str] = None
    tools_path: Optional[str] = None

    # Storage
    storage_backend: Optional["StorageBackend"] = None

    # Per-item context
    current_item: Optional[Dict[str, Any]] = None
    record_index: int = 0

    @classmethod
    def from_processing_context(cls, context: "ProcessingContext") -> "PreparationContext":
        """
        Create PreparationContext from a ProcessingContext.

        Args:
            context: ProcessingContext to convert

        Returns:
            PreparationContext with equivalent fields
        """
        from agent_actions.utils.tools_resolver import resolve_tools_path

        return cls(
            agent_config=context.agent_config,
            agent_name=context.agent_name,
            is_first_stage=context.is_first_stage,
            is_batch_mode=False,  # Online/realtime mode
            source_data=context.source_data,
            agent_indices=context.agent_indices,
            dependency_configs=context.dependency_configs,
            workflow_metadata=context.workflow_metadata,
            version_context=context.version_context,
            file_path=context.file_path,
            output_directory=context.output_directory,
            tools_path=resolve_tools_path(context.agent_config),
            storage_backend=context.storage_backend,
            current_item=context.current_item,
            record_index=context.record_index,
        )


# Import ProcessingContext for type checking and from_processing_context
if TYPE_CHECKING:
    from agent_actions.processing.types import ProcessingContext

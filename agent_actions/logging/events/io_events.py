"""File I/O, schema operations, and context introspection events (FIO/SO/CX prefixes)."""

from dataclasses import dataclass, field

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories

__all__ = [
    "SourceDataSavingEvent",
    "SourceDataSavedEvent",
    "SchemaLoadingStartedEvent",
    "SchemaLoadedEvent",
    "FileWriteStartedEvent",
    "FileWriteCompleteEvent",
    "SchemaConstructionStartedEvent",
    "SchemaConstructionCompleteEvent",
    "ContextNamespaceLoadedEvent",
    "ContextFieldSkippedEvent",
    "ContextScopeAppliedEvent",
    "ContextDependencyInferredEvent",
    "ContextFieldNotFoundEvent",
]


@dataclass
class SourceDataSavingEvent(BaseEvent):
    """Fired before saving source data to file."""

    file_path: str = ""
    item_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.FILE_IO
        self.message = f"Saving {self.item_count} items to {self.file_path}"
        self.data = {
            "file_path": self.file_path,
            "item_count": self.item_count,
        }

    @property
    def code(self) -> str:
        return "FIO001"


@dataclass
class SourceDataSavedEvent(BaseEvent):
    """Fired after source data is saved to file."""

    file_path: str = ""
    item_count: int = 0
    bytes_written: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.FILE_IO
        size_kb = self.bytes_written / 1024 if self.bytes_written > 0 else 0
        self.message = f"Saved {self.item_count} items to {self.file_path} ({size_kb:.1f}KB)"
        self.data = {
            "file_path": self.file_path,
            "item_count": self.item_count,
            "bytes_written": self.bytes_written,
        }

    @property
    def code(self) -> str:
        return "FIO002"


@dataclass
class SchemaLoadingStartedEvent(BaseEvent):
    """Fired when schema loading starts."""

    schema_name: str = ""
    schema_path: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.FILE_IO
        self.message = f"Loading schema: {self.schema_name}"
        self.data = {
            "schema_name": self.schema_name,
            "schema_path": self.schema_path,
        }

    @property
    def code(self) -> str:
        return "FIO003"


@dataclass
class SchemaLoadedEvent(BaseEvent):
    """Fired when schema is loaded successfully."""

    schema_name: str = ""
    field_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.FILE_IO
        self.message = f"Loaded schema: {self.schema_name} ({self.field_count} fields)"
        self.data = {
            "schema_name": self.schema_name,
            "field_count": self.field_count,
        }

    @property
    def code(self) -> str:
        return "FIO004"


@dataclass
class FileWriteStartedEvent(BaseEvent):
    """Fired when file write operation starts."""

    file_path: str = ""
    file_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.FILE_IO
        self.message = f"Writing {self.file_type} file: {self.file_path}"
        self.data = {
            "file_path": self.file_path,
            "file_type": self.file_type,
        }

    @property
    def code(self) -> str:
        return "FIO005"


@dataclass
class FileWriteCompleteEvent(BaseEvent):
    """Fired when file write operation completes."""

    file_path: str = ""
    file_type: str = ""
    bytes_written: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.FILE_IO
        size_kb = self.bytes_written / 1024 if self.bytes_written > 0 else 0
        self.message = f"Wrote {self.file_type} file: {self.file_path} ({size_kb:.1f}KB)"
        self.data = {
            "file_path": self.file_path,
            "file_type": self.file_type,
            "bytes_written": self.bytes_written,
        }

    @property
    def code(self) -> str:
        return "FIO006"


@dataclass
class SchemaConstructionStartedEvent(BaseEvent):
    """Fired when schema construction starts."""

    schema_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.SCHEMA
        self.message = f"Constructing schema from {self.schema_type}"
        self.data = {
            "schema_type": self.schema_type,
        }

    @property
    def code(self) -> str:
        return "SO001"


@dataclass
class SchemaConstructionCompleteEvent(BaseEvent):
    """Fired when schema construction completes."""

    schema_type: str = ""
    field_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.SCHEMA
        self.message = f"Constructed schema from {self.schema_type} ({self.field_count} fields)"
        self.data = {
            "schema_type": self.schema_type,
            "field_count": self.field_count,
        }

    @property
    def code(self) -> str:
        return "SO002"


@dataclass
class ContextNamespaceLoadedEvent(BaseEvent):
    """Fired when a namespace is loaded into context."""

    action_name: str = ""
    namespace: str = ""
    field_count: int = 0
    fields: list[str] = field(default_factory=list)
    dropped_fields: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA
        dropped_str = f" ({len(self.dropped_fields)} dropped)" if self.dropped_fields else ""
        self.message = (
            f"[{self.action_name}] Loaded namespace '{self.namespace}': "
            f"{self.field_count} fields{dropped_str}"
        )
        self.data = {
            "action_name": self.action_name,
            "namespace": self.namespace,
            "field_count": self.field_count,
            "fields": self.fields,
            "dropped_fields": self.dropped_fields,
        }

    @property
    def code(self) -> str:
        return "CX001"


@dataclass
class ContextFieldSkippedEvent(BaseEvent):
    """Fired when an invalid field reference is skipped."""

    action_name: str = ""
    field_ref: str = ""
    reason: str = ""
    directive: str = ""  # observe, drop, passthrough

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.DATA
        self.message = (
            f"[{self.action_name}] Skipped field '{self.field_ref}' "
            f"in {self.directive}: {self.reason}"
        )
        self.data = {
            "action_name": self.action_name,
            "field_ref": self.field_ref,
            "reason": self.reason,
            "directive": self.directive,
        }

    @property
    def code(self) -> str:
        return "CX002"


@dataclass
class ContextScopeAppliedEvent(BaseEvent):
    """Fired when context scope rules are applied."""

    action_name: str = ""
    observe_count: int = 0
    passthrough_count: int = 0
    drop_count: int = 0
    observe_fields: list[str] = field(default_factory=list)
    passthrough_fields: list[str] = field(default_factory=list)
    drop_fields: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA
        self.message = (
            f"[{self.action_name}] Applied context scope: "
            f"{self.observe_count} observe, {self.passthrough_count} passthrough, "
            f"{self.drop_count} drop"
        )
        self.data = {
            "action_name": self.action_name,
            "observe_count": self.observe_count,
            "passthrough_count": self.passthrough_count,
            "drop_count": self.drop_count,
            "observe_fields": self.observe_fields,
            "passthrough_fields": self.passthrough_fields,
            "drop_fields": self.drop_fields,
        }

    @property
    def code(self) -> str:
        return "CX003"


@dataclass
class ContextDependencyInferredEvent(BaseEvent):
    """Fired when dependencies are auto-inferred from context_scope."""

    action_name: str = ""
    input_sources: list[str] = field(default_factory=list)
    context_sources: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA
        self.message = (
            f"[{self.action_name}] Inferred dependencies: "
            f"{len(self.input_sources)} input, {len(self.context_sources)} context"
        )
        self.data = {
            "action_name": self.action_name,
            "input_sources": self.input_sources,
            "context_sources": self.context_sources,
        }

    @property
    def code(self) -> str:
        return "CX005"


@dataclass
class ContextFieldNotFoundEvent(BaseEvent):
    """Fired when a referenced field is not found in the available data."""

    action_name: str = ""
    field_ref: str = ""
    namespace: str = ""
    available_fields: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.DATA
        available_str = ", ".join(self.available_fields[:5])
        if len(self.available_fields) > 5:
            available_str += f"... (+{len(self.available_fields) - 5} more)"
        self.message = (
            f"[{self.action_name}] Field '{self.field_ref}' not found in '{self.namespace}'. "
            f"Available: {available_str}"
        )
        self.data = {
            "action_name": self.action_name,
            "field_ref": self.field_ref,
            "namespace": self.namespace,
            "available_fields": self.available_fields,
        }

    @property
    def code(self) -> str:
        return "CX006"

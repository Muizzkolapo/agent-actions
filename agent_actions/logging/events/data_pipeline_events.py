"""Data validation, transformation, record processing, batch processing, and result collection events (DV/DT/RP/BP/RC prefixes)."""

from dataclasses import dataclass, field
from typing import Any

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories

__all__ = [
    "DataValidationStartedEvent",
    "DataValidationPassedEvent",
    "DataValidationFailedEvent",
    "EnrichmentPipelineStartedEvent",
    "EnricherExecutedEvent",
    "EnrichmentPipelineCompleteEvent",
    "DataNormalizationStartedEvent",
    "DataNormalizedEvent",
    "RecordProcessingStartedEvent",
    "RecordFilteredEvent",
    "RecordTransformedEvent",
    "RecordProcessingCompleteEvent",
    "RecordEmptyOutputEvent",
    "BatchProcessingStartedEvent",
    "BatchProcessingProgressEvent",
    "BatchDataProcessingCompleteEvent",
    "ResultCollectionStartedEvent",
    "ResultCollectedEvent",
    "ResultCollectionCompleteEvent",
    "ExhaustedRecordEvent",
]


@dataclass
class DataValidationStartedEvent(BaseEvent):
    """Fired when data validation starts."""

    validator_type: str = ""
    target: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.VALIDATION
        self.message = f"Data validation started: {self.validator_type} on {self.target}"
        self.data = {
            "validator_type": self.validator_type,
            "target": self.target,
        }

    @property
    def code(self) -> str:
        return "DV001"


@dataclass
class DataValidationPassedEvent(BaseEvent):
    """Fired when data validation passes."""

    validator_type: str = ""
    item_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.VALIDATION
        self.message = f"Data validation passed: {self.validator_type} ({self.item_count} items)"
        self.data = {
            "validator_type": self.validator_type,
            "item_count": self.item_count,
        }

    @property
    def code(self) -> str:
        return "DV002"


@dataclass
class DataValidationFailedEvent(BaseEvent):
    """Fired when data validation fails."""

    validator_type: str = ""
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.VALIDATION
        error_summary = f"{len(self.errors)} error(s)" if self.errors else "validation failed"
        self.message = f"Data validation failed: {self.validator_type} - {error_summary}"
        self.data = {
            "validator_type": self.validator_type,
            "errors": self.errors,
            "error_count": len(self.errors),
        }

    @property
    def code(self) -> str:
        return "DV003"


@dataclass
class EnrichmentPipelineStartedEvent(BaseEvent):
    """Fired when enrichment pipeline starts."""

    enricher_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"Enrichment pipeline started with {self.enricher_count} enrichers"
        self.data = {
            "enricher_count": self.enricher_count,
        }

    @property
    def code(self) -> str:
        return "DT001"


@dataclass
class EnricherExecutedEvent(BaseEvent):
    """Fired when an enricher executes."""

    enricher_name: str = ""
    status: str = "success"

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"Enricher executed: {self.enricher_name} ({self.status})"
        self.data = {
            "enricher_name": self.enricher_name,
            "status": self.status,
        }

    @property
    def code(self) -> str:
        return "DT002"


@dataclass
class EnrichmentPipelineCompleteEvent(BaseEvent):
    """Fired when enrichment pipeline completes."""

    enricher_count: int = 0
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"Enrichment pipeline complete ({self.enricher_count} enrichers in {self.elapsed_time:.3f}s)"
        self.data = {
            "enricher_count": self.enricher_count,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "DT003"


@dataclass
class DataNormalizationStartedEvent(BaseEvent):
    """Fired when data normalization starts."""

    data_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"Data normalization started for {self.data_type}"
        self.data = {
            "data_type": self.data_type,
        }

    @property
    def code(self) -> str:
        return "DT004"


@dataclass
class DataNormalizedEvent(BaseEvent):
    """Fired when data is normalized."""

    data_type: str = ""
    item_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"Data normalized: {self.data_type} ({self.item_count} items)"
        self.data = {
            "data_type": self.data_type,
            "item_count": self.item_count,
        }

    @property
    def code(self) -> str:
        return "DT005"


@dataclass
class RecordProcessingStartedEvent(BaseEvent):
    """Fired when record processing starts."""

    action_name: str = ""
    record_index: int = 0
    source_guid: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"[{self.action_name}] Processing record {self.record_index}"
        self.data = {
            "action_name": self.action_name,
            "record_index": self.record_index,
            "source_guid": self.source_guid,
        }

    @property
    def code(self) -> str:
        return "RP001"


@dataclass
class RecordFilteredEvent(BaseEvent):
    """Fired when a record is filtered by guard."""

    action_name: str = ""
    record_index: int = 0
    source_guid: str = ""
    filter_reason: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = (
            f"[{self.action_name}] Record {self.record_index} filtered: {self.filter_reason}"
        )
        self.data = {
            "action_name": self.action_name,
            "record_index": self.record_index,
            "source_guid": self.source_guid,
            "filter_reason": self.filter_reason,
        }

    @property
    def code(self) -> str:
        return "RP002"


@dataclass
class RecordTransformedEvent(BaseEvent):
    """Fired when a record is transformed."""

    action_name: str = ""
    record_index: int = 0
    source_guid: str = ""
    input_size: int = 0
    output_size: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"[{self.action_name}] Record {self.record_index} transformed: {self.input_size} -> {self.output_size} items"
        self.data = {
            "action_name": self.action_name,
            "record_index": self.record_index,
            "source_guid": self.source_guid,
            "input_size": self.input_size,
            "output_size": self.output_size,
        }

    @property
    def code(self) -> str:
        return "RP003"


@dataclass
class RecordProcessingCompleteEvent(BaseEvent):
    """Fired when record processing completes."""

    action_name: str = ""
    record_index: int = 0
    source_guid: str = ""
    status: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = (
            f"[{self.action_name}] Record {self.record_index} processing complete: {self.status}"
        )
        self.data = {
            "action_name": self.action_name,
            "record_index": self.record_index,
            "source_guid": self.source_guid,
            "status": self.status,
        }

    @property
    def code(self) -> str:
        return "RP004"


@dataclass
class RecordEmptyOutputEvent(BaseEvent):
    """Fired when an action produces empty output for a record."""

    action_name: str = ""
    record_index: int = 0
    source_guid: str = ""
    input_field_count: int = 0
    output: Any = None
    on_empty: str = "warn"

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.DATA_PROCESSING
        self.message = (
            f"[{self.action_name}] Record {self.record_index} produced empty output "
            f"(source_guid={self.source_guid}, input had {self.input_field_count} fields). "
            f"Downstream actions depending on this will receive no data."
        )
        self.data = {
            "action_name": self.action_name,
            "record_index": self.record_index,
            "source_guid": self.source_guid,
            "input_field_count": self.input_field_count,
            "output": str(self.output),
            "on_empty": self.on_empty,
        }

    @property
    def code(self) -> str:
        return "RP005"


@dataclass
class BatchProcessingStartedEvent(BaseEvent):
    """Fired when batch processing starts."""

    action_name: str = ""
    batch_size: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"[{self.action_name}] Starting batch processing: {self.batch_size} records"
        self.data = {
            "action_name": self.action_name,
            "batch_size": self.batch_size,
        }

    @property
    def code(self) -> str:
        return "BP001"


@dataclass
class BatchProcessingProgressEvent(BaseEvent):
    """Fired periodically during batch processing."""

    action_name: str = ""
    processed: int = 0
    total: int = 0
    successes: int = 0
    failures: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"[{self.action_name}] Batch progress: {self.processed}/{self.total} ({self.successes} success, {self.failures} failures)"
        self.data = {
            "action_name": self.action_name,
            "processed": self.processed,
            "total": self.total,
            "successes": self.successes,
            "failures": self.failures,
        }

    @property
    def code(self) -> str:
        return "BP002"


@dataclass
class BatchDataProcessingCompleteEvent(BaseEvent):
    """Fired when batch data processing completes."""

    action_name: str = ""
    total_records: int = 0
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"[{self.action_name}] Batch processing complete: {self.total_records} records in {self.elapsed_time:.2f}s"
        self.data = {
            "action_name": self.action_name,
            "total_records": self.total_records,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "BP003"


@dataclass
class ResultCollectionStartedEvent(BaseEvent):
    """Fired when result collection starts."""

    action_name: str = ""
    total_results: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = (
            f"[{self.action_name}] Starting result collection: {self.total_results} results"
        )
        self.data = {
            "action_name": self.action_name,
            "total_results": self.total_results,
        }

    @property
    def code(self) -> str:
        return "RC001"


@dataclass
class ResultCollectedEvent(BaseEvent):
    """Fired when a result is collected."""

    action_name: str = ""
    result_index: int = 0
    status: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"[{self.action_name}] Result {self.result_index} collected: {self.status}"
        self.data = {
            "action_name": self.action_name,
            "result_index": self.result_index,
            "status": self.status,
        }

    @property
    def code(self) -> str:
        return "RC002"


@dataclass
class ResultCollectionCompleteEvent(BaseEvent):
    """Fired when result collection completes."""

    action_name: str = ""
    total_success: int = 0
    total_skipped: int = 0
    total_filtered: int = 0
    total_failed: int = 0
    total_exhausted: int = 0
    total_unprocessed: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.DATA_PROCESSING
        self.message = (
            f"[{self.action_name}] Result collection complete: "
            f"{self.total_success} success, {self.total_skipped} skipped, "
            f"{self.total_filtered} filtered, {self.total_failed} failed, "
            f"{self.total_exhausted} exhausted, {self.total_unprocessed} unprocessed"
        )
        self.data = {
            "action_name": self.action_name,
            "total_success": self.total_success,
            "total_skipped": self.total_skipped,
            "total_filtered": self.total_filtered,
            "total_failed": self.total_failed,
            "total_exhausted": self.total_exhausted,
            "total_unprocessed": self.total_unprocessed,
        }

    @property
    def code(self) -> str:
        return "RC003"


@dataclass
class ExhaustedRecordEvent(BaseEvent):
    """Fired when a record is exhausted (retry/reprompt failed)."""

    action_name: str = ""
    record_index: int = 0
    source_guid: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.DATA_PROCESSING
        self.message = f"[{self.action_name}] Record {self.record_index} exhausted: {self.reason}"
        self.data = {
            "action_name": self.action_name,
            "record_index": self.record_index,
            "source_guid": self.source_guid,
            "reason": self.reason,
        }

    @property
    def code(self) -> str:
        return "RC004"

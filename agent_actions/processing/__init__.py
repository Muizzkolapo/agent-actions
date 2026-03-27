"""Core processing types and abstractions for unified record processing."""

from .enrichment import (
    Enricher,
    EnrichmentPipeline,
    LineageEnricher,
    MetadataEnricher,
    PassthroughEnricher,
    RequiredFieldsEnricher,
    VersionIdEnricher,
)
from .invocation import (
    BatchProvider,
    BatchStrategy,
    BatchSubmissionResult,
    InvocationResult,
    InvocationStrategy,
    InvocationStrategyFactory,
    OnlineStrategy,
)
from .prepared_task import (
    GuardStatus,
    PreparationContext,
    PreparedTask,
)
from .processor import RecordProcessor
from .task_preparer import (
    TaskPreparer,
    get_task_preparer,
    reset_task_preparer,
)
from .types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
    RetryState,
)

__all__ = [
    # Types
    "ProcessingContext",
    "ProcessingMode",
    "ProcessingResult",
    "ProcessingStatus",
    "RetryState",
    # Prepared Task (Phase 2)
    "GuardStatus",
    "PreparedTask",
    "PreparationContext",
    "TaskPreparer",
    "get_task_preparer",
    "reset_task_preparer",
    # Invocation Strategies (Phase 3)
    "BatchProvider",
    "InvocationResult",
    "InvocationStrategy",
    "OnlineStrategy",
    "BatchStrategy",
    "BatchSubmissionResult",
    "InvocationStrategyFactory",
    # Enrichment
    "Enricher",
    "EnrichmentPipeline",
    "LineageEnricher",
    "VersionIdEnricher",
    "MetadataEnricher",
    "PassthroughEnricher",
    "RequiredFieldsEnricher",
    # Processing
    "RecordProcessor",
]

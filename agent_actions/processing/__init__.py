"""Core processing types and abstractions for unified record processing."""

from .enrichment import (
    Enricher,
    EnrichmentPipeline,
    LineageEnricher,
    VersionIdEnricher,
    MetadataEnricher,
    PassthroughEnricher,
    RequiredFieldsEnricher,
)
from .invocation import (
    BatchProvider,
    InvocationResult,
    InvocationStrategy,
    OnlineStrategy,
    BatchStrategy,
    BatchSubmissionResult,
    InvocationStrategyFactory,
)
from .prepared_task import (
    GuardStatus,
    PreparedTask,
    PreparationContext,
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

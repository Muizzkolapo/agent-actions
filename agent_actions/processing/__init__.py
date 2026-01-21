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
from .processor import RecordProcessor
from .result_adapters import ProcessingResultAdapter
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
    # Adapters
    "ProcessingResultAdapter",
]

"""
Unified metadata system for batch and online modes.

This module provides consistent metadata extraction and tracking across
all processing pipelines, ensuring structural consistency between batch
and online mode outputs.

Example:
    >>> from agent_actions.utilities.metadata import MetadataExtractor, MetadataTimer
    >>>
    >>> # Extract metadata from LLM response
    >>> with MetadataTimer() as timer:
    ...     response = llm.generate(prompt)
    >>> metadata = MetadataExtractor.extract_from_response(
    ...     response=response,
    ...     provider="openai",
    ...     latency_ms=timer.elapsed_ms
    ... )
    >>> item["metadata"] = metadata.to_dict()
"""

from .metadata_types import ResponseMetadata, RetryMetadata, UnifiedMetadata
from .metadata_extractor import MetadataExtractor, MetadataTimer

__all__ = [
    "ResponseMetadata",
    "RetryMetadata",
    "UnifiedMetadata",
    "MetadataExtractor",
    "MetadataTimer",
]

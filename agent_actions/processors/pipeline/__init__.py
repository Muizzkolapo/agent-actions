"""Pipeline pattern implementation for data transformations."""

from .interfaces import (
    IPipelineStage,
    IPipeline,
    PipelineContext,
    StageResult,
    ValidationError,
    TransformationError
)

from .pipeline import Pipeline
from .stage_registry import StageRegistry
from .stages import (
    ValidationStage,
    TransformationStage,
    EnrichmentStage,
    NormalizationStage
)

__all__ = [
    # Interfaces
    'IPipelineStage',
    'IPipeline',
    'PipelineContext',
    'StageResult',
    'ValidationError',
    'TransformationError',
    
    # Implementation
    'Pipeline',
    'StageRegistry',
    
    # Built-in stages
    'ValidationStage',
    'TransformationStage', 
    'EnrichmentStage',
    'NormalizationStage'
]
"""Interfaces for the pipeline pattern implementation."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypeVar, Generic, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class StageStatus(Enum):
    """Status of a pipeline stage execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ValidationError(Exception):
    """Raised when data validation fails in a pipeline stage."""
    def __init__(self, message: str, stage_name: str, errors: List[Dict[str, Any]]):
        super().__init__(message)
        self.stage_name = stage_name
        self.errors = errors


class TransformationError(Exception):
    """Raised when a transformation fails in a pipeline stage."""
    def __init__(self, message: str, stage_name: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.stage_name = stage_name
        self.original_error = original_error


@dataclass
class StageResult:
    """Result of a pipeline stage execution."""
    stage_name: str
    status: StageStatus
    data: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Exception] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    @property
    def duration(self) -> Optional[float]:
        """Calculate duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


@dataclass
class PipelineContext:
    """Context passed through pipeline stages."""
    data: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    stage_results: List[StageResult] = field(default_factory=list)
    
    def add_result(self, result: StageResult):
        """Add a stage result to the context."""
        self.stage_results.append(result)
    
    def get_stage_result(self, stage_name: str) -> Optional[StageResult]:
        """Get result from a specific stage."""
        for result in self.stage_results:
            if result.stage_name == stage_name:
                return result
        return None
    
    def set_metadata(self, key: str, value: Any):
        """Set metadata value."""
        self.metadata[key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata value."""
        return self.metadata.get(key, default)


T = TypeVar('T')
R = TypeVar('R')


class IPipelineStage(ABC, Generic[T, R]):
    """Interface for a pipeline stage."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this stage."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Return a description of what this stage does."""
        pass
    
    @abstractmethod
    def validate_input(self, data: T) -> List[Dict[str, Any]]:
        """
        Validate input data for this stage.
        
        Args:
            data: Input data to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        pass
    
    @abstractmethod
    def transform(self, data: T, context: PipelineContext) -> R:
        """
        Transform the input data.
        
        Args:
            data: Input data to transform
            context: Pipeline context with metadata
            
        Returns:
            Transformed data
            
        Raises:
            TransformationError: If transformation fails
        """
        pass
    
    def validate_output(self, data: R) -> List[Dict[str, Any]]:
        """
        Validate output data from this stage.
        
        Args:
            data: Output data to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        return []  # Default: no output validation
    
    async def transform_async(self, data: T, context: PipelineContext) -> R:
        """
        Async version of transform. Default uses sync version.
        
        Args:
            data: Input data to transform
            context: Pipeline context with metadata
            
        Returns:
            Transformed data
        """
        import asyncio
        return await asyncio.to_thread(self.transform, data, context)


class IPipeline(ABC):
    """Interface for a data processing pipeline."""
    
    @abstractmethod
    def add_stage(self, stage: IPipelineStage) -> 'IPipeline':
        """
        Add a stage to the pipeline.
        
        Args:
            stage: Stage to add
            
        Returns:
            Self for method chaining
        """
        pass
    
    @abstractmethod
    def remove_stage(self, stage_name: str) -> 'IPipeline':
        """
        Remove a stage from the pipeline.
        
        Args:
            stage_name: Name of stage to remove
            
        Returns:
            Self for method chaining
        """
        pass
    
    @abstractmethod
    def execute(self, data: Any, metadata: Optional[Dict[str, Any]] = None) -> PipelineContext:
        """
        Execute the pipeline on input data.
        
        Args:
            data: Input data to process
            metadata: Optional metadata for the pipeline context
            
        Returns:
            Final pipeline context with results
            
        Raises:
            ValidationError: If validation fails
            TransformationError: If transformation fails
        """
        pass
    
    @abstractmethod
    async def execute_async(self, data: Any, metadata: Optional[Dict[str, Any]] = None) -> PipelineContext:
        """
        Execute the pipeline asynchronously.
        
        Args:
            data: Input data to process
            metadata: Optional metadata for the pipeline context
            
        Returns:
            Final pipeline context with results
        """
        pass
    
    @abstractmethod
    def get_stages(self) -> List[IPipelineStage]:
        """Get all stages in the pipeline."""
        pass
    
    @abstractmethod
    def validate_pipeline(self) -> List[Dict[str, Any]]:
        """
        Validate the pipeline configuration.
        
        Returns:
            List of validation errors (empty if valid)
        """
        pass


class IStageBuilder(ABC):
    """Interface for building pipeline stages."""
    
    @abstractmethod
    def with_validator(self, validator: Callable[[Any], List[Dict[str, Any]]]) -> 'IStageBuilder':
        """Add input validator to the stage."""
        pass
    
    @abstractmethod
    def with_transformer(self, transformer: Callable[[Any, PipelineContext], Any]) -> 'IStageBuilder':
        """Add transformer function to the stage."""
        pass
    
    @abstractmethod
    def with_output_validator(self, validator: Callable[[Any], List[Dict[str, Any]]]) -> 'IStageBuilder':
        """Add output validator to the stage."""
        pass
    
    @abstractmethod
    def build(self) -> IPipelineStage:
        """Build the stage."""
        pass
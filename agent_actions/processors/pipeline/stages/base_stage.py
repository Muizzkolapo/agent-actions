"""Base stage implementation with common functionality."""

from typing import Any, Dict, List, Optional, Callable
from ..interfaces import IPipelineStage, PipelineContext


class BaseStage(IPipelineStage):
    """
    Base implementation for pipeline stages.
    
    Provides common functionality and default implementations.
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        input_validator: Optional[Callable[[Any], List[Dict[str, Any]]]] = None,
        output_validator: Optional[Callable[[Any], List[Dict[str, Any]]]] = None
    ):
        """
        Initialize base stage.
        
        Args:
            name: Name of the stage
            description: Description of what this stage does
            input_validator: Optional custom input validator
            output_validator: Optional custom output validator
        """
        self._name = name
        self._description = description
        self._input_validator = input_validator
        self._output_validator = output_validator
    
    @property
    def name(self) -> str:
        """Return the name of this stage."""
        return self._name
    
    @property
    def description(self) -> str:
        """Return a description of what this stage does."""
        return self._description
    
    def validate_input(self, data: Any) -> List[Dict[str, Any]]:
        """
        Validate input data for this stage.
        
        Uses custom validator if provided, otherwise returns empty list.
        """
        if self._input_validator:
            return self._input_validator(data)
        return []
    
    def validate_output(self, data: Any) -> List[Dict[str, Any]]:
        """
        Validate output data from this stage.
        
        Uses custom validator if provided, otherwise returns empty list.
        """
        if self._output_validator:
            return self._output_validator(data)
        return []
    
    def transform(self, data: Any, context: PipelineContext) -> Any:
        """
        Transform the input data. Must be implemented by subclasses.
        """
        raise NotImplementedError(f"Stage '{self.name}' must implement transform method")
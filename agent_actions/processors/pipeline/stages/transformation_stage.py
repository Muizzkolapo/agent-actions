"""Transformation stage for data pipeline."""

from typing import Any, Dict, List, Callable, Optional
import copy

from .base_stage import BaseStage
from ..interfaces import PipelineContext, TransformationError
from ..stage_registry import register_stage


@register_stage("transformation")
class TransformationStage(BaseStage):
    """
    Stage that transforms data using pure functions.
    
    This stage applies transformations without side effects,
    ensuring data immutability and predictable behavior.
    """
    
    def __init__(
        self,
        name: str = "transformation",
        description: str = "Transforms data structure",
        transformer: Optional[Callable[[Any, PipelineContext], Any]] = None,
        transformations: Optional[List[Callable[[Any], Any]]] = None,
        deep_copy: bool = True
    ):
        """
        Initialize transformation stage.
        
        Args:
            name: Name of the stage
            description: Description of the stage
            transformer: Main transformation function
            transformations: List of transformation functions to apply in sequence
            deep_copy: Whether to deep copy data before transformation
        """
        super().__init__(name, description)
        self.transformer = transformer
        self.transformations = transformations or []
        self.deep_copy = deep_copy
    
    def transform(self, data: Any, context: PipelineContext) -> Any:
        """
        Transform the input data using pure functions.
        
        Args:
            data: Input data to transform
            context: Pipeline context
            
        Returns:
            Transformed data
            
        Raises:
            TransformationError: If transformation fails
        """
        try:
            # Deep copy to ensure immutability
            if self.deep_copy:
                working_data = copy.deepcopy(data)
            else:
                working_data = data
            
            # Apply main transformer if provided
            if self.transformer:
                working_data = self.transformer(working_data, context)
            
            # Apply sequential transformations
            for transform_func in self.transformations:
                working_data = transform_func(working_data)
            
            return working_data
            
        except Exception as e:
            raise TransformationError(
                f"Transformation failed: {str(e)}",
                stage_name=self.name,
                original_error=e
            )


class PureTransformations:
    """Collection of pure transformation functions."""
    
    @staticmethod
    def flatten_list_of_dicts(data: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Flatten a nested list of dictionaries.
        
        Args:
            data: Nested list structure
            
        Returns:
            Flattened list of dictionaries
        """
        if not isinstance(data, list):
            return data
        
        flattened = []
        for item in data:
            if isinstance(item, list):
                flattened.extend(item)
            else:
                flattened.append(item)
        return flattened
    
    @staticmethod
    def extract_field(field_name: str) -> Callable[[Dict[str, Any]], Any]:
        """
        Create a function to extract a specific field from dictionaries.
        
        Args:
            field_name: Name of field to extract
            
        Returns:
            Extraction function
        """
        def extractor(data: Dict[str, Any]) -> Any:
            if isinstance(data, dict):
                return data.get(field_name)
            return data
        return extractor
    
    @staticmethod
    def map_structure(mapping: Dict[str, str]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """
        Create a function to map dictionary keys.
        
        Args:
            mapping: Dictionary mapping old keys to new keys
            
        Returns:
            Mapping function
        """
        def mapper(data: Dict[str, Any]) -> Dict[str, Any]:
            if not isinstance(data, dict):
                return data
            
            result = {}
            for old_key, new_key in mapping.items():
                if old_key in data:
                    result[new_key] = data[old_key]
            
            # Keep unmapped keys
            for key, value in data.items():
                if key not in mapping and key not in result:
                    result[key] = value
            
            return result
        return mapper
    
    @staticmethod
    def filter_fields(fields_to_keep: List[str]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """
        Create a function to filter dictionary fields.
        
        Args:
            fields_to_keep: List of field names to keep
            
        Returns:
            Filter function
        """
        def filter_func(data: Dict[str, Any]) -> Dict[str, Any]:
            if not isinstance(data, dict):
                return data
            
            return {k: v for k, v in data.items() if k in fields_to_keep}
        return filter_func
    
    @staticmethod
    def remove_fields(fields_to_remove: List[str]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """
        Create a function to remove dictionary fields.
        
        Args:
            fields_to_remove: List of field names to remove
            
        Returns:
            Removal function
        """
        def remove_func(data: Dict[str, Any]) -> Dict[str, Any]:
            if not isinstance(data, dict):
                return data
            
            result = data.copy()
            for field in fields_to_remove:
                result.pop(field, None)
            return result
        return remove_func
    
    @staticmethod
    def merge_objects(merge_with: Dict[str, Any]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """
        Create a function to merge dictionaries.
        
        Args:
            merge_with: Dictionary to merge into data
            
        Returns:
            Merge function
        """
        def merge_func(data: Dict[str, Any]) -> Dict[str, Any]:
            if not isinstance(data, dict):
                return data
            
            result = data.copy()
            result.update(merge_with)
            return result
        return merge_func


class TransformationBuilder:
    """Builder for creating transformation stages."""
    
    def __init__(self, name: str = "transformation"):
        self.name = name
        self.description = "Transforms data"
        self.transformer = None
        self.transformations = []
        self.deep_copy = True
    
    def with_transformer(self, transformer: Callable[[Any, PipelineContext], Any]) -> 'TransformationBuilder':
        """Set main transformation function."""
        self.transformer = transformer
        return self
    
    def add_transformation(self, transformation: Callable[[Any], Any]) -> 'TransformationBuilder':
        """Add a transformation to the sequence."""
        self.transformations.append(transformation)
        return self
    
    def flatten_lists(self) -> 'TransformationBuilder':
        """Add list flattening transformation."""
        self.transformations.append(PureTransformations.flatten_list_of_dicts)
        return self
    
    def extract_field(self, field_name: str) -> 'TransformationBuilder':
        """Add field extraction transformation."""
        self.transformations.append(PureTransformations.extract_field(field_name))
        return self
    
    def map_fields(self, mapping: Dict[str, str]) -> 'TransformationBuilder':
        """Add field mapping transformation."""
        self.transformations.append(PureTransformations.map_structure(mapping))
        return self
    
    def filter_fields(self, fields: List[str]) -> 'TransformationBuilder':
        """Add field filtering transformation."""
        self.transformations.append(PureTransformations.filter_fields(fields))
        return self
    
    def remove_fields(self, fields: List[str]) -> 'TransformationBuilder':
        """Add field removal transformation."""
        self.transformations.append(PureTransformations.remove_fields(fields))
        return self
    
    def with_deep_copy(self, deep_copy: bool) -> 'TransformationBuilder':
        """Set whether to deep copy data."""
        self.deep_copy = deep_copy
        return self
    
    def build(self) -> TransformationStage:
        """Build the transformation stage."""
        return TransformationStage(
            name=self.name,
            description=self.description,
            transformer=self.transformer,
            transformations=self.transformations,
            deep_copy=self.deep_copy
        )
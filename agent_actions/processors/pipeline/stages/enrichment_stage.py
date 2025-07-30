"""Enrichment stage for data pipeline."""

from typing import Any, Dict, List, Optional, Callable
import uuid
from datetime import datetime

from .base_stage import BaseStage
from ..interfaces import PipelineContext, TransformationError
from ..stage_registry import register_stage


@register_stage("enrichment")
class EnrichmentStage(BaseStage):
    """
    Stage that enriches data with additional information.
    
    This stage adds computed fields, metadata, and external data
    without modifying existing fields.
    """
    
    def __init__(
        self,
        name: str = "enrichment",
        description: str = "Enriches data with additional information",
        enrichers: Optional[Dict[str, Callable[[Any, PipelineContext], Any]]] = None,
        metadata_fields: Optional[Dict[str, Any]] = None,
        computed_fields: Optional[Dict[str, Callable[[Dict[str, Any]], Any]]] = None,
        add_timestamps: bool = False,
        add_id: bool = False
    ):
        """
        Initialize enrichment stage.
        
        Args:
            name: Name of the stage
            description: Description of the stage
            enrichers: Dict of field names to enrichment functions
            metadata_fields: Static metadata to add to each item
            computed_fields: Dict of field names to computation functions
            add_timestamps: Whether to add created_at/updated_at timestamps
            add_id: Whether to add unique ID to each item
        """
        super().__init__(name, description)
        self.enrichers = enrichers or {}
        self.metadata_fields = metadata_fields or {}
        self.computed_fields = computed_fields or {}
        self.add_timestamps = add_timestamps
        self.add_id = add_id
    
    def transform(self, data: Any, context: PipelineContext) -> Any:
        """
        Enrich the input data.
        
        Args:
            data: Input data to enrich
            context: Pipeline context
            
        Returns:
            Enriched data
            
        Raises:
            TransformationError: If enrichment fails
        """
        try:
            if isinstance(data, list):
                return [self._enrich_item(item, context) for item in data]
            else:
                return self._enrich_item(data, context)
                
        except Exception as e:
            raise TransformationError(
                f"Enrichment failed: {str(e)}",
                stage_name=self.name,
                original_error=e
            )
    
    def _enrich_item(self, item: Any, context: PipelineContext) -> Any:
        """Enrich a single data item."""
        if not isinstance(item, dict):
            return item
        
        # Create a copy to avoid modifying original
        enriched = item.copy()
        
        # Add ID if requested
        if self.add_id and 'id' not in enriched:
            enriched['id'] = str(uuid.uuid4())
        
        # Add timestamps if requested
        if self.add_timestamps:
            now = datetime.utcnow().isoformat()
            if 'created_at' not in enriched:
                enriched['created_at'] = now
            enriched['updated_at'] = now
        
        # Add static metadata fields
        for field, value in self.metadata_fields.items():
            if field not in enriched:
                enriched[field] = value
        
        # Apply enrichers
        for field, enricher_func in self.enrichers.items():
            try:
                enriched[field] = enricher_func(item, context)
            except Exception as e:
                # Log error but continue
                context.set_metadata(
                    f"{self.name}_enricher_errors",
                    f"Failed to enrich field '{field}': {str(e)}"
                )
        
        # Apply computed fields
        for field, compute_func in self.computed_fields.items():
            try:
                enriched[field] = compute_func(enriched)
            except Exception as e:
                # Log error but continue
                context.set_metadata(
                    f"{self.name}_compute_errors",
                    f"Failed to compute field '{field}': {str(e)}"
                )
        
        return enriched


class EnrichmentFunctions:
    """Collection of common enrichment functions."""
    
    @staticmethod
    def add_source_metadata(source: str) -> Callable[[Any, PipelineContext], Dict[str, Any]]:
        """Create function to add source metadata."""
        def enricher(item: Any, context: PipelineContext) -> Dict[str, Any]:
            return {
                'source': source,
                'pipeline': context.get_metadata('pipeline_name'),
                'processed_at': datetime.utcnow().isoformat()
            }
        return enricher
    
    @staticmethod
    def add_lineage(parent_field: str = 'parent_id') -> Callable[[Any, PipelineContext], str]:
        """Create function to add data lineage."""
        def enricher(item: Dict[str, Any], context: PipelineContext) -> str:
            parent_id = item.get(parent_field, 'root')
            stage_name = context.get_metadata('current_stage', 'unknown')
            return f"{parent_id}/{stage_name}"
        return enricher
    
    @staticmethod
    def compute_field_count(item: Dict[str, Any]) -> int:
        """Compute number of non-null fields."""
        return sum(1 for v in item.values() if v is not None)
    
    @staticmethod
    def compute_completeness(required_fields: List[str]) -> Callable[[Dict[str, Any]], float]:
        """Create function to compute data completeness percentage."""
        def compute(item: Dict[str, Any]) -> float:
            if not required_fields:
                return 100.0
            
            present = sum(1 for field in required_fields if item.get(field) is not None)
            return (present / len(required_fields)) * 100
        return compute
    
    @staticmethod
    def concat_fields(*fields: str, separator: str = ' ') -> Callable[[Dict[str, Any]], str]:
        """Create function to concatenate multiple fields."""
        def compute(item: Dict[str, Any]) -> str:
            values = [str(item.get(f, '')) for f in fields if item.get(f) is not None]
            return separator.join(values)
        return compute
    
    @staticmethod
    def hash_field(field: str, algorithm: str = 'sha256') -> Callable[[Dict[str, Any]], str]:
        """Create function to hash a field value."""
        import hashlib
        
        def compute(item: Dict[str, Any]) -> str:
            value = item.get(field)
            if value is None:
                return None
            
            hasher = getattr(hashlib, algorithm)()
            hasher.update(str(value).encode('utf-8'))
            return hasher.hexdigest()
        return compute


class EnrichmentBuilder:
    """Builder for creating enrichment stages."""
    
    def __init__(self, name: str = "enrichment"):
        self.name = name
        self.description = "Enriches data"
        self.enrichers = {}
        self.metadata_fields = {}
        self.computed_fields = {}
        self.add_timestamps = False
        self.add_id = False
    
    def add_enricher(self, field: str, enricher: Callable[[Any, PipelineContext], Any]) -> 'EnrichmentBuilder':
        """Add enricher function for a field."""
        self.enrichers[field] = enricher
        return self
    
    def add_metadata(self, field: str, value: Any) -> 'EnrichmentBuilder':
        """Add static metadata field."""
        self.metadata_fields[field] = value
        return self
    
    def add_computed_field(self, field: str, compute_func: Callable[[Dict[str, Any]], Any]) -> 'EnrichmentBuilder':
        """Add computed field."""
        self.computed_fields[field] = compute_func
        return self
    
    def with_timestamps(self, add: bool = True) -> 'EnrichmentBuilder':
        """Add created_at/updated_at timestamps."""
        self.add_timestamps = add
        return self
    
    def with_id(self, add: bool = True) -> 'EnrichmentBuilder':
        """Add unique ID to items."""
        self.add_id = add
        return self
    
    def add_source_metadata(self, source: str) -> 'EnrichmentBuilder':
        """Add source metadata enricher."""
        self.enrichers['_metadata'] = EnrichmentFunctions.add_source_metadata(source)
        return self
    
    def add_lineage(self, field: str = 'lineage') -> 'EnrichmentBuilder':
        """Add lineage tracking."""
        self.enrichers[field] = EnrichmentFunctions.add_lineage()
        return self
    
    def add_completeness(self, field: str, required_fields: List[str]) -> 'EnrichmentBuilder':
        """Add completeness calculation."""
        self.computed_fields[field] = EnrichmentFunctions.compute_completeness(required_fields)
        return self
    
    def concat_to_field(self, new_field: str, *source_fields: str, separator: str = ' ') -> 'EnrichmentBuilder':
        """Concatenate fields into new field."""
        self.computed_fields[new_field] = EnrichmentFunctions.concat_fields(*source_fields, separator=separator)
        return self
    
    def hash_field(self, source_field: str, hash_field: str, algorithm: str = 'sha256') -> 'EnrichmentBuilder':
        """Add field hashing."""
        self.computed_fields[hash_field] = EnrichmentFunctions.hash_field(source_field, algorithm)
        return self
    
    def build(self) -> EnrichmentStage:
        """Build the enrichment stage."""
        return EnrichmentStage(
            name=self.name,
            description=self.description,
            enrichers=self.enrichers,
            metadata_fields=self.metadata_fields,
            computed_fields=self.computed_fields,
            add_timestamps=self.add_timestamps,
            add_id=self.add_id
        )
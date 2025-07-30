"""Adapters to migrate existing transformations to pipeline pattern."""

from typing import Any, Dict, List, Optional
import logging

from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.transformers.pure_transformers import PureDataTransformer
from .pipeline import Pipeline
from .stages import TransformationStage, ValidationStage, EnrichmentStage
from .interfaces import PipelineContext


logger = logging.getLogger(__name__)


class DataTransformerAdapter:
    """
    Adapter to use existing DataTransformer methods with the pipeline pattern.
    
    This provides backward compatibility while migrating to pure functions.
    """
    
    @staticmethod
    def create_update_schema_stage(
        keys_to_update: List[str],
        stage_name: str = "update_schema"
    ) -> TransformationStage:
        """
        Create a pipeline stage for update_schema_objects transformation.
        
        Args:
            keys_to_update: Keys to update in the schema
            stage_name: Name for the stage
            
        Returns:
            TransformationStage configured for schema updates
        """
        def transformer(data: Any, context: PipelineContext) -> Any:
            # Get old data from context if available
            old_data = context.get_metadata("old_data")
            if not old_data:
                logger.warning("No old_data found in context for schema update")
                return data
            
            if isinstance(data, list):
                # Process list of items
                return [
                    PureDataTransformer.update_schema_objects(
                        old_data.get(i, {}), item, keys_to_update
                    )
                    for i, item in enumerate(data)
                ]
            else:
                # Process single item
                return PureDataTransformer.update_schema_objects(
                    old_data, data, keys_to_update
                )
        
        return TransformationStage(
            name=stage_name,
            description=f"Updates schema objects for keys: {keys_to_update}",
            transformer=transformer
        )
    
    @staticmethod
    def create_remove_fields_stage(
        keys_to_remove: List[str],
        stage_name: str = "remove_fields"
    ) -> TransformationStage:
        """
        Create a pipeline stage for removing fields.
        
        Args:
            keys_to_remove: Keys to remove from data
            stage_name: Name for the stage
            
        Returns:
            TransformationStage configured for field removal
        """
        def transformer(data: Any, context: PipelineContext) -> Any:
            if isinstance(data, list):
                return [
                    PureDataTransformer.remove_schema_objects(item, keys_to_remove)
                    if isinstance(item, dict) else item
                    for item in data
                ]
            elif isinstance(data, dict):
                return PureDataTransformer.remove_schema_objects(data, keys_to_remove)
            else:
                return data
        
        return TransformationStage(
            name=stage_name,
            description=f"Removes fields: {keys_to_remove}",
            transformer=transformer
        )
    
    @staticmethod
    def create_extract_objects_stage(
        stage_name: str = "extract_objects"
    ) -> TransformationStage:
        """
        Create a pipeline stage for extracting nested objects.
        
        Returns:
            TransformationStage configured for object extraction
        """
        def transformer(data: Any, context: PipelineContext) -> Any:
            return PureDataTransformer.extract_objects(data)
        
        return TransformationStage(
            name=stage_name,
            description="Extracts nested objects from data structure",
            transformer=transformer
        )
    
    @staticmethod
    def create_flatten_stage(
        stage_name: str = "flatten_lists"
    ) -> TransformationStage:
        """
        Create a pipeline stage for flattening nested lists.
        
        Returns:
            TransformationStage configured for list flattening
        """
        def transformer(data: Any, context: PipelineContext) -> Any:
            if isinstance(data, list):
                return PureDataTransformer.flatten_to_list_of_dicts(data)
            return data
        
        return TransformationStage(
            name=stage_name,
            description="Flattens nested list structures",
            transformer=transformer
        )
    
    @staticmethod
    def create_transform_structure_stage(
        stage_name: str = "transform_structure"
    ) -> TransformationStage:
        """
        Create a pipeline stage for structure transformation.
        
        Returns:
            TransformationStage configured for structure transformation
        """
        def transformer(data: Any, context: PipelineContext) -> Any:
            if isinstance(data, list):
                return PureDataTransformer.transform_structure(data)
            return data
        
        return TransformationStage(
            name=stage_name,
            description="Transforms nested structure to flat list",
            transformer=transformer
        )
    
    @staticmethod
    def create_legacy_compatible_pipeline(
        name: str = "legacy_transformer"
    ) -> Pipeline:
        """
        Create a pipeline that mimics the behavior of the original DataTransformer.
        
        This helps with gradual migration from the old pattern.
        
        Returns:
            Pipeline configured to match legacy behavior
        """
        pipeline = Pipeline(
            name=name,
            description="Legacy-compatible data transformation pipeline"
        )
        
        # Add stages that replicate common DataTransformer usage patterns
        
        # Stage 1: Extract nested objects
        extract_stage = DataTransformerAdapter.create_extract_objects_stage()
        
        # Stage 2: Flatten if needed
        flatten_stage = DataTransformerAdapter.create_flatten_stage()
        
        # Stage 3: Transform structure
        transform_stage = DataTransformerAdapter.create_transform_structure_stage()
        
        return pipeline.add_stage(extract_stage) \
                       .add_stage(flatten_stage) \
                       .add_stage(transform_stage)


class ProcessorToPipelineAdapter:
    """
    Adapter to convert existing processor logic to pipeline stages.
    """
    
    @staticmethod
    def create_validation_stage_from_config(
        agent_config: Dict[str, Any],
        stage_name: str = "config_validation"
    ) -> ValidationStage:
        """
        Create validation stage from agent configuration.
        
        Args:
            agent_config: Agent configuration dict
            stage_name: Name for the validation stage
            
        Returns:
            ValidationStage configured from agent config
        """
        # Extract validation rules from config
        schema = agent_config.get("validation_schema", {})
        required_fields = agent_config.get("required_fields", [])
        
        # Build schema if only required fields are specified
        if required_fields and not schema:
            schema = {
                "type": "object",
                "required": required_fields,
                "properties": {
                    field: {"type": ["string", "number", "object", "array", "boolean", "null"]}
                    for field in required_fields
                }
            }
        
        return ValidationStage(
            name=stage_name,
            description="Validates data against agent configuration",
            schema=schema if schema else None
        )
    
    @staticmethod
    def create_enrichment_stage_from_config(
        agent_config: Dict[str, Any],
        agent_name: str,
        idx: int,
        stage_name: str = "config_enrichment"
    ) -> EnrichmentStage:
        """
        Create enrichment stage from agent configuration.
        
        Args:
            agent_config: Agent configuration dict
            agent_name: Name of the agent
            idx: Index of the processor
            stage_name: Name for the enrichment stage
            
        Returns:
            EnrichmentStage configured from agent config
        """
        metadata_fields = {
            "agent_name": agent_name,
            "processor_idx": idx,
            "processing_mode": agent_config.get("run_mode", "sync")
        }
        
        # Add any custom metadata from config
        custom_metadata = agent_config.get("metadata", {})
        metadata_fields.update(custom_metadata)
        
        return EnrichmentStage(
            name=stage_name,
            description="Enriches data with agent metadata",
            metadata_fields=metadata_fields,
            add_timestamps=agent_config.get("add_timestamps", False),
            add_id=agent_config.get("add_id", False)
        )
    
    @staticmethod
    def migrate_processor_to_pipeline(
        processor_class: type,
        agent_config: Dict[str, Any],
        agent_name: str,
        idx: int
    ) -> Pipeline:
        """
        Migrate an existing processor class to use the pipeline pattern.
        
        Args:
            processor_class: The processor class to migrate
            agent_config: Agent configuration
            agent_name: Name of the agent
            idx: Processor index
            
        Returns:
            Pipeline that replicates the processor's behavior
        """
        pipeline = Pipeline(
            name=f"{processor_class.__name__}_pipeline",
            description=f"Pipeline migration of {processor_class.__name__}"
        )
        
        # Add validation stage
        validation = ProcessorToPipelineAdapter.create_validation_stage_from_config(
            agent_config
        )
        pipeline.add_stage(validation)
        
        # Add transformation stages based on processor type
        if hasattr(processor_class, '_get_transformation_stages'):
            # If processor defines its own transformation stages
            stages = processor_class._get_transformation_stages(agent_config)
            for stage in stages:
                pipeline.add_stage(stage)
        else:
            # Default transformation pipeline
            pipeline.add_stage(DataTransformerAdapter.create_extract_objects_stage())
            
            # Add remove fields if configured
            if "remove_fields" in agent_config:
                pipeline.add_stage(
                    DataTransformerAdapter.create_remove_fields_stage(
                        agent_config["remove_fields"]
                    )
                )
        
        # Add enrichment stage
        enrichment = ProcessorToPipelineAdapter.create_enrichment_stage_from_config(
            agent_config, agent_name, idx
        )
        pipeline.add_stage(enrichment)
        
        return pipeline
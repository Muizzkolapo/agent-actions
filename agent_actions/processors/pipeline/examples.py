"""Example usage of the pipeline pattern."""

from typing import Dict, List, Any

from .pipeline import Pipeline
from .stages import (
    ValidationStage,
    NormalizationStage,
    TransformationStage,
    EnrichmentStage
)
from .stages.validation_stage import SchemaValidationBuilder
from .stages.normalization_stage import NormalizationBuilder
from .stages.transformation_stage import TransformationBuilder, PureTransformations
from .stages.enrichment_stage import EnrichmentBuilder


def create_data_processing_pipeline() -> Pipeline:
    """
    Create a complete data processing pipeline with all stages.
    
    This demonstrates how to compose stages for a typical data flow.
    """
    # Create pipeline
    pipeline = Pipeline(
        name="data_processor",
        description="Processes raw data through validation, normalization, transformation, and enrichment"
    )
    
    # Stage 1: Validation
    validation_stage = SchemaValidationBuilder("input_validation") \
        .with_schema({
            "type": "object",
            "properties": {
                "source_guid": {"type": "string"},
                "content": {"type": "object"},
                "timestamp": {"type": "string"}
            },
            "required": ["source_guid", "content"]
        }) \
        .with_strict_mode(True) \
        .build()
    
    # Stage 2: Normalization
    normalization_stage = NormalizationBuilder("normalize_data") \
        .convert_field("timestamp", str) \
        .set_default("status", "pending") \
        .set_default("priority", 5) \
        .normalize_field("source_guid", lambda x: x.strip().lower()) \
        .with_strip_whitespace(True) \
        .build()
    
    # Stage 3: Transformation
    transformation_stage = TransformationBuilder("transform_structure") \
        .map_fields({
            "source_guid": "id",
            "content": "data",
            "timestamp": "created_at"
        }) \
        .remove_fields(["_internal", "_temp"]) \
        .build()
    
    # Stage 4: Enrichment
    enrichment_stage = EnrichmentBuilder("enrich_metadata") \
        .add_metadata("version", "1.0") \
        .add_metadata("processor", "agent_actions") \
        .with_timestamps(True) \
        .with_id(False) \
        .add_completeness("completeness", ["id", "data", "status"]) \
        .add_lineage("lineage") \
        .build()
    
    # Compose pipeline
    pipeline.add_stage(validation_stage) \
            .add_stage(normalization_stage) \
            .add_stage(transformation_stage) \
            .add_stage(enrichment_stage)
    
    return pipeline


def create_simple_transformation_pipeline() -> Pipeline:
    """Create a simple pipeline focused on data transformation."""
    pipeline = Pipeline(name="simple_transformer")
    
    # Just transformation and enrichment
    transform = TransformationBuilder("flatten") \
        .flatten_lists() \
        .filter_fields(["id", "name", "value"]) \
        .build()
    
    enrich = EnrichmentBuilder("add_metadata") \
        .with_id(True) \
        .with_timestamps(True) \
        .build()
    
    return pipeline.add_stage(transform).add_stage(enrich)


def create_agent_response_pipeline() -> Pipeline:
    """
    Create a pipeline specifically for processing agent responses.
    
    This replaces the complex transformation logic in response_transformer.py.
    """
    pipeline = Pipeline(name="agent_response_processor")
    
    # Validate agent response
    validation = ValidationStage(
        name="validate_response",
        schema={
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "object"}
                }
            }
        }
    )
    
    # Normalize response data
    normalize = NormalizationBuilder("normalize_response") \
        .set_default("status", "processed") \
        .set_default("error", None) \
        .with_strip_whitespace(True) \
        .build()
    
    # Transform structure for downstream processing
    transform = TransformationStage(
        name="restructure_response",
        transformer=lambda data, ctx: [
            {
                "source_guid": ctx.get_metadata("source_guid"),
                "content": item,
                "agent_name": ctx.get_metadata("agent_name")
            }
            for item in data
        ]
    )
    
    # Enrich with metadata
    enrich = EnrichmentBuilder("enrich_response") \
        .add_metadata("processing_stage", "response") \
        .add_computed_field("item_count", lambda x: len(x.get("content", {}))) \
        .with_timestamps(True) \
        .build()
    
    return pipeline.add_stage(validation) \
                   .add_stage(normalize) \
                   .add_stage(transform) \
                   .add_stage(enrich)


def demonstrate_pipeline_usage():
    """Demonstrate how to use the pipeline."""
    # Create pipeline
    pipeline = create_data_processing_pipeline()
    
    # Sample input data
    input_data = [
        {
            "source_guid": "  ABC123  ",
            "content": {"text": "Hello world", "type": "greeting"},
            "timestamp": "2024-01-01",
            "_internal": "should be removed"
        },
        {
            "source_guid": "DEF456",
            "content": {"text": "Test message", "type": "test"}
            # Missing timestamp - will get default
        }
    ]
    
    # Execute pipeline
    context = pipeline.execute(input_data)
    
    # Access results
    final_data = context.data
    stage_results = context.stage_results
    
    # Print results
    print(f"Pipeline: {pipeline.name}")
    print(f"Stages executed: {len(stage_results)}")
    
    for result in stage_results:
        print(f"\nStage: {result.stage_name}")
        print(f"Status: {result.status.value}")
        print(f"Duration: {result.duration:.3f}s")
    
    print(f"\nFinal data: {final_data}")
    
    return final_data


async def demonstrate_async_pipeline():
    """Demonstrate async pipeline execution."""
    # Create pipeline
    pipeline = create_data_processing_pipeline()
    
    # Sample data
    input_data = [{"source_guid": f"item_{i}", "content": {"value": i}} for i in range(100)]
    
    # Execute asynchronously
    context = await pipeline.execute_async(input_data)
    
    print(f"Processed {len(context.data)} items asynchronously")
    return context.data


if __name__ == "__main__":
    # Run demonstration
    demonstrate_pipeline_usage()
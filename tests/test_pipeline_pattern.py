"""Tests for the pipeline pattern implementation."""

import pytest
import json
from typing import Dict, List, Any

from agent_actions.processors.pipeline import (
    Pipeline,
    ValidationStage,
    TransformationStage,
    NormalizationStage,
    EnrichmentStage,
    PipelineContext,
    ValidationError,
    TransformationError
)
from agent_actions.processors.pipeline.validation import (
    DataFlowValidator,
    DataFlowMonitor,
    ValidationLevel
)
from agent_actions.processors.pipeline.examples import (
    create_data_processing_pipeline,
    create_agent_response_pipeline
)
from agent_actions.common.transformers.pure_transformers import PureDataTransformer


class TestPipeline:
    """Test the basic pipeline functionality."""
    
    def test_simple_pipeline(self):
        """Test a simple pipeline with two stages."""
        # Create pipeline
        pipeline = Pipeline("test_pipeline")
        
        # Add validation stage
        validation = ValidationStage(
            name="validate",
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"}
                },
                "required": ["name", "value"]
            }
        )
        
        # Add transformation stage
        transform = TransformationStage(
            name="transform",
            transformer=lambda data, ctx: {**data, "processed": True}
        )
        
        pipeline.add_stage(validation).add_stage(transform)
        
        # Execute pipeline
        input_data = {"name": "test", "value": 42}
        context = pipeline.execute(input_data)
        
        assert context.data == {"name": "test", "value": 42, "processed": True}
        assert len(context.stage_results) == 2
        assert all(r.status.value == "success" for r in context.stage_results)
    
    def test_pipeline_validation_error(self):
        """Test pipeline handling validation errors."""
        pipeline = Pipeline("test_pipeline")
        
        validation = ValidationStage(
            name="validate",
            schema={
                "type": "object",
                "required": ["required_field"]
            },
            strict=True
        )
        
        pipeline.add_stage(validation)
        
        # Execute with invalid data
        with pytest.raises(ValidationError) as exc_info:
            pipeline.execute({"other_field": "value"})
        
        assert "Input validation failed" in str(exc_info.value)
    
    def test_pipeline_transformation_error(self):
        """Test pipeline handling transformation errors."""
        pipeline = Pipeline("test_pipeline")
        
        # Add stage that raises error
        def failing_transformer(data, ctx):
            raise ValueError("Transform failed")
        
        transform = TransformationStage(
            name="failing_transform",
            transformer=failing_transformer
        )
        
        pipeline.add_stage(transform)
        
        with pytest.raises(TransformationError) as exc_info:
            pipeline.execute({"data": "test"})
        
        assert "Transform failed" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_async_pipeline(self):
        """Test async pipeline execution."""
        pipeline = Pipeline("async_test")
        
        # Add async-capable stages
        transform = TransformationStage(
            name="async_transform",
            transformer=lambda data, ctx: [{"id": i, **item} for i, item in enumerate(data)]
        )
        
        pipeline.add_stage(transform)
        
        # Execute asynchronously
        input_data = [{"name": f"item_{i}"} for i in range(10)]
        context = await pipeline.execute_async(input_data)
        
        assert len(context.data) == 10
        assert all("id" in item for item in context.data)


class TestPipelineStages:
    """Test individual pipeline stages."""
    
    def test_normalization_stage(self):
        """Test normalization stage functionality."""
        normalize = NormalizationStage(
            name="normalize",
            type_conversions={"age": int, "active": bool},
            default_values={"status": "pending"},
            strip_whitespace=True,
            lowercase_keys=True
        )
        
        input_data = {
            "Name": "  John Doe  ",
            "AGE": "25",
            "active": "true"
        }
        
        context = PipelineContext(data=input_data)
        result = normalize.transform(input_data, context)
        
        assert result == {
            "name": "John Doe",
            "age": 25,
            "active": True,
            "status": "pending"
        }
    
    def test_enrichment_stage(self):
        """Test enrichment stage functionality."""
        enrich = EnrichmentStage(
            name="enrich",
            metadata_fields={"source": "test"},
            computed_fields={
                "full_name": lambda x: f"{x.get('first_name', '')} {x.get('last_name', '')}"
            },
            add_timestamps=True,
            add_id=True
        )
        
        input_data = {"first_name": "John", "last_name": "Doe"}
        context = PipelineContext(data=input_data)
        result = enrich.transform(input_data, context)
        
        assert result["source"] == "test"
        assert result["full_name"] == "John Doe"
        assert "id" in result
        assert "created_at" in result
        assert "updated_at" in result
    
    def test_transformation_stage_with_pure_functions(self):
        """Test transformation stage using pure functions."""
        # Test remove fields
        transform = TransformationStage(
            name="remove_internal",
            transformer=lambda data, ctx: PureDataTransformer.remove_schema_objects(
                data, ["_internal", "_temp"]
            )
        )
        
        input_data = {
            "public": "value",
            "_internal": "hidden",
            "_temp": "temporary"
        }
        
        context = PipelineContext(data=input_data)
        result = transform.transform(input_data, context)
        
        assert result == {"public": "value"}
        assert "_internal" not in result
        assert "_temp" not in result


class TestDataFlowValidation:
    """Test data flow validation functionality."""
    
    def test_flow_validator(self):
        """Test data flow validation."""
        validator = DataFlowValidator(ValidationLevel.STRICT)
        
        # Register schemas
        validator.register_stage_schema(
            "input",
            output_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "data": {"type": "object"}
                },
                "required": ["id", "data"]
            }
        )
        
        validator.register_stage_schema(
            "transform",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "data": {"type": "object"}
                },
                "required": ["id"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "processed_data": {"type": "object"}
                },
                "required": ["id", "processed_data"]
            }
        )
        
        # Create pipeline
        pipeline = Pipeline("test_flow")
        
        input_stage = TransformationStage(name="input")
        transform_stage = TransformationStage(name="transform")
        
        pipeline.add_stage(input_stage).add_stage(transform_stage)
        
        # Validate flow
        result = validator.validate_pipeline_flow(pipeline)
        
        # Should have warnings about potential field loss
        assert len(result.warnings) > 0
    
    def test_flow_monitor(self):
        """Test data flow monitoring."""
        monitor = DataFlowMonitor()
        
        # Simulate stage executions
        input_data = [{"id": 1, "name": "test"}]
        output_data = [{"id": 1, "name": "test", "processed": True}]
        
        monitor.monitor_stage_execution(
            "transform",
            input_data,
            output_data,
            0.1
        )
        
        # Get report
        report = monitor.get_report()
        
        assert "transform" in report["stage_metrics"]
        assert report["stage_metrics"]["transform"]["executions"] == 1
        assert "id" in report["field_usage"]
        assert "name" in report["field_usage"]
        assert "processed" in report["field_usage"]


class TestPipelineExamples:
    """Test the example pipelines."""
    
    def test_data_processing_pipeline(self):
        """Test the complete data processing pipeline example."""
        pipeline = create_data_processing_pipeline()
        
        # Test data
        input_data = {
            "source_guid": "test123",
            "content": {"message": "Hello"},
            "timestamp": "2024-01-01"
        }
        
        context = pipeline.execute(input_data)
        
        # Check transformations applied
        assert "id" in context.data  # source_guid mapped to id
        assert "data" in context.data  # content mapped to data
        assert "version" in context.data  # metadata added
        assert "completeness" in context.data  # computed field added
    
    def test_agent_response_pipeline(self):
        """Test the agent response processing pipeline."""
        pipeline = create_agent_response_pipeline()
        
        # Test data
        input_data = [
            {"content": {"result": "success"}},
            {"content": {"result": "pending"}}
        ]
        
        # Add required metadata
        metadata = {
            "source_guid": "agent123",
            "agent_name": "test_agent"
        }
        
        context = pipeline.execute(input_data, metadata)
        
        # Check all items processed
        assert len(context.data) == 2
        assert all("source_guid" in item for item in context.data)
        assert all("agent_name" in item for item in context.data)
        assert all("created_at" in item for item in context.data)


class TestPureTransformers:
    """Test pure transformer functions."""
    
    def test_update_schema_objects(self):
        """Test pure schema update function."""
        old_data = {"field1": "old_value", "field2": 42}
        new_data = {"field1": "new_value", "field3": "extra"}
        keys_to_update = ["field1", "field2"]
        
        result = PureDataTransformer.update_schema_objects(
            old_data, new_data, keys_to_update
        )
        
        assert result["field1"] == "old_value"  # Updated from old
        assert result["field2"] == 42  # Added from old
        assert result["field3"] == "extra"  # Kept from new
        
        # Original data unchanged
        assert new_data["field1"] == "new_value"
    
    def test_filter_by_condition(self):
        """Test pure filtering function."""
        data = [
            {"id": 1, "active": True},
            {"id": 2, "active": False},
            {"id": 3, "active": True}
        ]
        
        matching, non_matching = PureDataTransformer.filter_by_condition(
            data, lambda x: x.get("active", False)
        )
        
        assert len(matching) == 2
        assert len(non_matching) == 1
        assert all(item["active"] for item in matching)
        assert not non_matching[0]["active"]
    
    def test_group_by_field(self):
        """Test pure grouping function."""
        data = [
            {"category": "A", "value": 1},
            {"category": "B", "value": 2},
            {"category": "A", "value": 3}
        ]
        
        grouped = PureDataTransformer.group_by_field(data, "category")
        
        assert len(grouped) == 2
        assert len(grouped["A"]) == 2
        assert len(grouped["B"]) == 1
        assert grouped["A"][0]["value"] == 1
        assert grouped["A"][1]["value"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
# Pipeline Pattern Migration Guide

## Overview

This guide explains how to migrate from the current complex data transformation flow to the new pipeline pattern, which provides:

- **Pure functions** with no side effects
- **Clear data flow** through composable stages
- **Better testability** and debugging
- **Type safety** and validation between stages

## Migration Steps

### 1. Understanding the Current Pattern

The current system has these issues:
- Multiple transformation steps with unclear purposes
- Side effects in transformation methods  
- Unclear data flow between processors
- Tight coupling between components

Example of current pattern:
```python
# Current approach - side effects and unclear flow
data = DataTransformer.update_schema_objects(old_data, new_data, keys)
data = DataTransformer.extract_objects(data)
data = DataTransformer.transform_structure(data)
```

### 2. New Pipeline Pattern

The new pattern uses composable stages:
```python
from agent_actions.processors.pipeline import Pipeline
from agent_actions.processors.pipeline.stages import *

# Create pipeline with clear stages
pipeline = Pipeline("data_processor")
    .add_stage(ValidationStage(...))
    .add_stage(NormalizationStage(...))
    .add_stage(TransformationStage(...))
    .add_stage(EnrichmentStage(...))

# Execute with clear context
context = pipeline.execute(input_data)
result = context.data
```

### 3. Migrating DataTransformer Methods

#### update_schema_objects → Pure Function + Pipeline Stage

**Before:**
```python
# Side effect - modifies data in place
updated = DataTransformer.update_schema_objects(old_data, new_data, keys)
```

**After:**
```python
from agent_actions.transformers.pure_transformers import PureDataTransformer
from agent_actions.processors.pipeline.adapters import DataTransformerAdapter

# Option 1: Use pure function directly
updated = PureDataTransformer.update_schema_objects(old_data, new_data, keys)

# Option 2: Use in pipeline
stage = DataTransformerAdapter.create_update_schema_stage(keys)
pipeline.add_stage(stage)
```

#### remove_schema_objects → TransformationStage

**Before:**
```python
cleaned = DataTransformer.remove_schema_objects(data, ["_internal", "_temp"])
```

**After:**
```python
# Create transformation stage
remove_stage = TransformationBuilder("remove_fields")
    .remove_fields(["_internal", "_temp"])
    .build()

pipeline.add_stage(remove_stage)
```

#### extract_objects + flatten → Pipeline Composition

**Before:**
```python
objects = DataTransformer.extract_objects(data)
flattened = DataTransformer.flatten_to_list_of_dicts(objects)
```

**After:**
```python
# Compose stages
pipeline = Pipeline("extract_and_flatten")
    .add_stage(DataTransformerAdapter.create_extract_objects_stage())
    .add_stage(DataTransformerAdapter.create_flatten_stage())
```

### 4. Migrating Processors

#### TargetContentProcessor → Pipeline-based Processor

**Before:**
```python
class TargetContentProcessor:
    def process(self, data, file_path):
        # Complex processing with side effects
        source_data = self.source_loader.load_source_data(file_path)
        processed_data = []
        
        for item in data:
            # Multiple transformations mixed together
            processed = self._process_single_item(item, source_data)
            processed_data.extend(processed)
        
        return processed_data
```

**After:**
```python
class TargetContentProcessor:
    def __init__(self):
        # Build pipeline in constructor
        self.pipeline = self._build_processing_pipeline()
    
    def _build_processing_pipeline(self):
        return Pipeline("target_processor")
            .add_stage(self._create_validation_stage())
            .add_stage(self._create_enrichment_stage())
            .add_stage(self._create_transformation_stage())
    
    def process(self, data, file_path):
        # Clean separation of concerns
        context = self.pipeline.execute(data, {
            "file_path": file_path,
            "source_data": self._load_source_data(file_path)
        })
        return context.data
```

### 5. Using Built-in Stages

#### ValidationStage
```python
# Schema validation
validation = SchemaValidationBuilder("validate_input")
    .with_schema({
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "data": {"type": "object"}
        },
        "required": ["id"]
    })
    .with_strict_mode(True)
    .build()
```

#### NormalizationStage
```python
# Data normalization
normalize = NormalizationBuilder("normalize")
    .convert_field("age", int)
    .set_default("status", "active")
    .normalize_emails("email", "contact_email")
    .normalize_phones("phone")
    .with_strip_whitespace(True)
    .build()
```

#### TransformationStage
```python
# Data transformation
transform = TransformationBuilder("transform")
    .map_fields({
        "source_guid": "id",
        "content": "data"
    })
    .remove_fields(["_internal"])
    .flatten_lists()
    .build()
```

#### EnrichmentStage
```python
# Data enrichment
enrich = EnrichmentBuilder("enrich")
    .add_metadata("version", "1.0")
    .with_timestamps(True)
    .with_id(True)
    .add_completeness("completeness", ["id", "name", "email"])
    .build()
```

### 6. Adding Data Flow Validation

```python
from agent_actions.processors.pipeline.validation import DataFlowValidator

# Create validator
validator = DataFlowValidator()

# Register expected schemas
validator.register_stage_schema(
    "input_stage",
    output_schema={...}
)

# Validate pipeline
result = validator.validate_pipeline_flow(pipeline)
if not result.is_valid:
    print(f"Validation errors: {result.errors}")
```

### 7. Monitoring Pipeline Execution

```python
from agent_actions.processors.pipeline.validation import DataFlowMonitor

# Create monitor
monitor = DataFlowMonitor()

# Execute with monitoring
pipeline.add_stage_interceptor("transform", 
    lambda ctx: monitor.monitor_stage_execution(...)
)

# Get insights
report = monitor.get_report()
print(f"Stage metrics: {report['stage_metrics']}")
print(f"Field usage: {report['field_usage']}")
```

## Best Practices

1. **Use Pure Functions**: All transformations should be side-effect free
2. **Single Responsibility**: Each stage should do one thing well
3. **Validate Early**: Add validation stages at the beginning
4. **Document Schemas**: Register schemas for each stage
5. **Monitor Performance**: Use DataFlowMonitor in production
6. **Test Stages Independently**: Each stage should be unit testable

## Common Patterns

### Conditional Processing
```python
def conditional_transform(data, context):
    if context.get_metadata("process_type") == "batch":
        return batch_transform(data)
    return regular_transform(data)

stage = TransformationStage(
    name="conditional",
    transformer=conditional_transform
)
```

### Error Recovery
```python
pipeline.add_error_handler("risky_stage", 
    lambda error, context: {
        "data": context.data,
        "error": str(error),
        "recovered": True
    }
)
```

### Parallel Processing
```python
# Async pipeline for better performance
context = await pipeline.execute_async(large_dataset)
```

## Gradual Migration Strategy

1. **Phase 1**: Wrap existing transformers with adapters
2. **Phase 2**: Replace simple transformations with pure functions
3. **Phase 3**: Refactor complex processors to use pipelines
4. **Phase 4**: Add validation and monitoring
5. **Phase 5**: Remove old transformation code

## Summary

The pipeline pattern provides:
- ✅ Clear, predictable data flow
- ✅ Pure functions without side effects
- ✅ Better error handling and recovery
- ✅ Comprehensive validation and monitoring
- ✅ Improved testability and maintainability

Start by migrating simple transformations and gradually work towards more complex processors. Use the adapters for backward compatibility during the transition.
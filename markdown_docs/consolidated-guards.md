# Consolidated Guards Configuration

## Overview

The consolidated guard system provides users with explicit control over how actions behave when guard conditions fail. This resolves the previous confusion between filtering records versus skipping agent execution.

## New Guard Format

### Basic Structure

```yaml
actions:
  - name: fact_extractor
    guard:
      condition: "udf:validators.should_extract_facts"
      on_false: "skip"  # Options: "skip" | "filter"
    # ... other action config
```

### Behavior Options

- **`skip`**: Agent doesn't process records, but they pass through with metadata (equivalent to old `conditional_clause`)
- **`filter`**: Records are completely removed from the workflow (equivalent to old `where_clause`)

### Future Extensions

The format is designed to be extensible for additional behaviors:

```yaml
# Future capabilities (not yet implemented)
guard:
  condition: "quality_score < 0.5"
  on_false: "write_to"
  write_target: "rejected_records.json"

# Or
guard:
  condition: "udf:validators.needs_review"
  on_false: "reprocess"
  reprocess_with: "human_review_agent"
```

## Condition Types

### UDF (User-Defined Function) Conditions

```yaml
guard:
  condition: "udf:validators.should_extract_facts"
  on_false: "skip"
```

- Uses `udf:` prefix
- Calls Python functions for dynamic evaluation
- Format: `udf:module.function`
- Security validated (dangerous patterns rejected)

### SQL-like Conditions

```yaml
guard:
  condition: 'questionable != "Low Value"'
  on_false: "filter"  # Can be "filter" or "skip"
```

- Standard comparison operators: `!=`, `==`, `>`, `<`, `>=`, `<=`
- Boolean operators: `AND`, `OR`
- Supports string and numeric comparisons
- Security validated
- **Both skip and filter behaviors supported**

## Behavior Details

### Skip Behavior

When `on_false: "skip"`:
- Agent execution is bypassed for records that fail the condition
- Records pass through to next stage with metadata:
  ```json
  {
    "original_data": "...",
    "metadata": {
      "skipped_by_conditional": true,
      "agent_type": "passthrough",
      "reason": "conditional_clause_failed"
    }
  }
  ```
- Workflow continues with all original records intact

### Filter Behavior

When `on_false: "filter"`:
- Records that fail the condition are completely removed
- Subsequent agents only see records that passed the filter
- No passthrough or metadata preservation

## Backward Compatibility

### Legacy String Format

Old guard formats are still supported:

```yaml
# Legacy UDF format (automatically becomes skip behavior)
guard: "udf:validators.should_process"

# Legacy SQL format (automatically becomes filter behavior)
guard: 'status == "active"'
```

### Migration Strategy

1. **UDF guards** (`udf:module.function`) automatically default to `skip` behavior
2. **SQL guards** (comparison expressions) automatically default to `filter` behavior
3. No breaking changes - existing workflows continue working

## Examples

### Quality Control with Skip (UDF)

```yaml
actions:
  - name: fact_extractor
    guard:
      condition: "udf:quality_checks.meets_standards"
      on_false: "skip"
    prompt: "Extract facts from: {content}"

  - name: fact_validator
    # Processes both extracted facts AND skipped records
    prompt: "Validate or flag: {content}"
```

### Quality Control with Skip (SQL)

```yaml
actions:
  - name: fact_extractor
    guard:
      condition: 'questionable != "Low Value"'
      on_false: "skip"  # SQL conditions now support skip!
    prompt: "Extract facts from: {content}"

  - name: fact_validator
    # Processes both high-quality facts AND low-quality skipped records
    prompt: "Validate or flag: {content}"
```

### Content Filtering

```yaml
actions:
  - name: content_filter
    guard:
      condition: 'content_type == "article" AND word_count > 100'
      on_false: "filter"

  - name: article_processor
    # Only processes records that passed the filter
    prompt: "Summarize article: {content}"
```

### Mixed Behaviors in Workflow

```yaml
actions:
  - name: quality_gate
    guard:
      condition: "udf:validators.basic_quality_check"
      on_false: "skip"  # Poor quality records skip processing but remain in dataset

  - name: spam_filter
    guard:
      condition: 'spam_score < 0.7'
      on_false: "filter"  # Spam records completely removed

  - name: content_processor
    # Processes: high-quality records + low-quality skipped records (no spam)
```

## Implementation Details

### Execution Flow

The consolidated guard system works consistently across both batch and non-batch workflows:

#### Batch Workflows
1. **Batch Service Level**: WHERE clauses with `filter` behavior are processed here
   - Records that fail filter conditions are removed entirely
   - WHERE clauses with `skip` behavior are passed through to agent level
2. **Agent Level**: All skip conditions are processed in `run_dynamic_agent()`
   - UDF guards (conditional_clause)
   - WHERE clauses with `skip` behavior
   - Skip conditions return original context unchanged

#### Non-Batch Workflows
1. **Agent Level Only**: All guard processing happens in `run_dynamic_agent()`
   - Same logic as batch workflows
   - Consistent behavior across all processing modes

#### Processing Logic
```python
def run_dynamic_agent(...):
    # 1. Handle legacy UDF skip behavior
    if conditional_clause and not execute_user_defined_function(...):
        return context, False  # Skip: original context unchanged

    # 2. Handle SQL skip behavior
    if where_clause["behavior"] == "skip" and not condition_matched:
        return context, False  # Skip: original context unchanged

    # 3. Process normally if no skip conditions triggered
    response = agent_builder.create_dynamic_agent(...)
    return response, True  # Processed: new response
```

### Security Validation

All guard conditions are validated for security:

- **Dangerous patterns rejected**: `__import__`, `exec`, `eval`, `compile`, `open`, etc.
- **UDF format validation**: Must follow `module.function` pattern
- **SQL injection prevention**: Basic pattern analysis

### Error Handling

- Invalid guard formats raise `ValueError` during workflow validation
- Runtime guard evaluation errors can be configured to pass through or fail
- Detailed error messages help with debugging

### Performance Considerations

- Filter behavior processed at batch service level (more efficient for large datasets)
- Skip behavior processed at agent level (consistent across all workflow types)
- UDF guards require Python function calls (slightly slower)
- SQL guards use lightweight expression evaluation
- Results are not cached (re-evaluated per record)

### Consistency Guarantee

**The same guard configuration produces identical behavior in both batch and non-batch workflows.**

This is achieved by:
- Using the same `run_dynamic_agent()` function for skip logic in both paths
- Consistent WHERE clause evaluation using the same filter service
- Identical error handling and passthrough behavior
- Same security validation across all processing modes

Whether your workflow processes 10 records or 10,000 records, whether using batch processing or direct processing, the guard behavior is guaranteed to be identical.

## Testing

### Unit Tests

The implementation includes comprehensive tests:

- `TestGuardConfig`: Basic configuration handling
- `TestConsolidatedGuardParser`: Format parsing
- `TestFormatConverterIntegration`: Workflow integration
- `TestSchemaValidation`: YAML validation

### Integration Tests

Run existing tests to ensure backward compatibility:

```bash
pytest tests/core/utils/test_guard_parser.py
pytest tests/core/parser/test_format_converter_guards.py
pytest tests/core/utils/test_consolidated_guard.py
```

## Migration Guide

### From conditional_clause

Old format:
```yaml
actions:
  - name: processor
    # This was confusing - skip or filter?
```

New format:
```yaml
actions:
  - name: processor
    guard:
      condition: "udf:validators.should_process"
      on_false: "skip"  # Explicit behavior
```

### From where_clause

Where clauses are now handled transparently by the format converter. No migration needed for basic cases.

## Future Enhancements

Planned extensions to the guard system:

1. **Write-to behavior**: Route failed records to specific outputs
2. **Reprocess behavior**: Send failed records to different agents
3. **Custom handlers**: User-defined failure handling functions
4. **Conditional routing**: Route based on multiple conditions
5. **Guard composition**: Combine multiple guard conditions

The consolidated format provides a foundation for these advanced features while maintaining the simple, explicit API.
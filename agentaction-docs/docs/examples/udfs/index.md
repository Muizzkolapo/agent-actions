---
title: UDF Examples
description: Real-world examples of User-Defined Functions with the @udf_tool decorator
sidebar_position: 10
---

# UDF Examples

Complete examples showing how to create and use User-Defined Functions (UDFs) with the `@udf_tool` decorator in your Agent Actions workflows.

## What are UDFs?

User-Defined Functions (UDFs) are custom Python functions that you write to extend Agent Actions functionality. They're used for:
- **Data validation**: Check data format, business rules, constraints
- **Data transformation**: Convert formats, enrich data, aggregate results
- **Custom logic**: Any processing you need that's specific to your use case

## Why Use @udf_tool?

The `@udf_tool` decorator provides automatic function discovery and registration:
- Reference functions by name only (no module paths)
- Auto-discovery from your user code directory
- Duplicate name detection at load time
- Better refactoring safety

## Quick Start

```python
# user_code/my_functions.py
from agent_actions import udf_tool

@udf_tool
def my_validator(data, **kwargs):
    """Validate data meets requirements."""
    # Your validation logic
    return data
```

```yaml
# agent_configs/my_agent.yml
actions:
  - name: validator
    impl: my_validator  # Just the function name!
    type: tool
```

## Example Categories

### [Basic UDF](./basic-udf)
Start here to learn the fundamentals:
- Creating your first UDF
- Using the decorator
- Referencing in configs
- Running workflows

### [Multiple Files](./multiple-files)
Learn how to organize UDFs:
- Directory structures
- Multiple files and modules
- Nested directories
- Avoiding name collisions

### [Validation UDFs](./validation-udfs)
Common validation patterns:
- Email and phone validation
- JSON structure validation
- Business rule validation
- Required field checks

### [Transformation UDFs](./transformation-udfs)
Data transformation examples:
- Format conversion (JSON ↔ CSV)
- Data enrichment
- Aggregation and filtering
- Complex data processing

## Related Documentation

- **[UDF Decorator Guide](/guides/udf-decorator)**: Complete guide to using `@udf_tool`
- **[CLI Reference](/cli-reference)**: `list-udfs` and `validate-udfs` commands
- **[Custom Validators](/examples/custom-validators)**: Additional validator examples
- **[Getting Started](/getting-started)**: First workflow tutorial

## Common Patterns

### Validator Pattern

```python
@udf_tool
def validate_format(data, **kwargs):
    """Validate and return data, or raise error."""
    if not is_valid(data):
        raise ValueError("Validation failed")
    return data
```

### Transformer Pattern

```python
@udf_tool
def transform_data(data, **kwargs):
    """Transform and return new data structure."""
    return {
        'transformed': True,
        'original': data,
        'processed_at': datetime.now().isoformat()
    }
```

### Enricher Pattern

```python
@udf_tool
def enrich_data(data, **kwargs):
    """Add additional fields to existing data."""
    data['enriched'] = True
    data['metadata'] = get_metadata()
    return data
```

## Next Steps

1. **Read the basics**: Start with [Basic UDF](./basic-udf)
2. **Explore patterns**: Check [Validation](./validation-udfs) and [Transformation](./transformation-udfs) examples
3. **Organize your code**: Learn from [Multiple Files](./multiple-files)
4. **Test your UDFs**: Use `list-udfs` and `validate-udfs` commands

Happy coding! 🚀

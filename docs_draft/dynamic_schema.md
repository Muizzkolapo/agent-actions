---
id: dynamic-schema
title: Dynamic Schema Dispatch
sidebar_label: Dynamic Schema
---

# Dynamic Schema Dispatch

The Dynamic Schema Dispatch feature allows you to populate schema fields dynamically at runtime using custom functions. This is particularly useful for scenarios where valid options for an enum, or validation constraints, depend on external data sources or runtime context.

## How It Works

You can use the `dispatch_task('function_name')` syntax within your schema YAML definition. When the schema is prepared for the agent, this syntax is replaced by the return value of the specified function.

### Example

```yaml
name: product_categorizer
schema:
  category:
    type: string
    description: The product category
    # Dynamically fetch categories from a database or API
    enum: "dispatch_task('get_valid_categories')"
```

## Functions

The dispatched functions reside in your `tools` directory (or wherever your `tool_path` points to). They receive the current `context_data` string as an argument.

```python
# tools/category_tools.py

def get_valid_categories(context_json):
    """Fetch valid categories from database."""
    # Logic to fetch categories
    return ["Electronics", "Clothing", "Home & Garden"]
```

## Recursive Resolution

The dispatch mechanism works recursively. You can use it nested within objects or lists.

```yaml
schema:
  metadata:
    type: object
    properties:
      region: 
        type: string
        # Dynamic default value
        default: "dispatch_task('get_default_region')"
```

## Capturing Results

If you enable `add_dispatch: true` in your agent configuration, `dispatch_task` results are also captured and merged into the final response alongside the LLM's output. This is useful if you want to reuse the dynamic data (e.g., the specific list of categories used) in downstream tasks.

```yaml
name: my_agent
add_dispatch: true
...
```

## Limitations

- The function must return a JSON-serializable value (string, number, list, dict) compatible with the schema field it replaces.
- The `dispatch_task` string must exactly match the value of the field for type preservation (e.g., `enum: "dispatch_task(...)"`). If embedded in a longer string (e.g., `description: "Choose from {dispatch_task(...)}"`), the result will constitute string interpolation.

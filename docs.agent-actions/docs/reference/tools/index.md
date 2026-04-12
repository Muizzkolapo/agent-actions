---
title: Tool Actions
sidebar_position: 1
---

# Tool Actions

What happens when you need logic that an LLM can't perform? Deduplicating records, calling an external API, or applying deterministic business rules—these tasks need deterministic logic, not prompts.

Tool actions let you execute custom Python functions alongside LLM actions in your agentic workflow. When you need guaranteed, repeatable behavior, you use a tool.

## Quick Example

```python
from agent_actions import udf_tool

@udf_tool()
def process_text(data: dict, **kwargs) -> dict:
    return {"result": data["text"].upper()}
```

```yaml
- name: process_step
  kind: tool
  impl: process_text
  granularity: record
```

## @udf_tool Decorator

The `@udf_tool` decorator registers a Python function as a tool action.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `granularity` | Granularity | No | `RECORD` (default) or `FILE` processing |

:::info Schema Definition
Input and output schemas are defined in the workflow YAML `schema:` field, not in the decorator.
:::

### Minimal Decorator

```python
from agent_actions import udf_tool

@udf_tool()
def simple_transform(data: dict, **kwargs) -> dict:
    data['processed'] = True
    return data
```

## Granularity

| Granularity | Processing | Use Case |
|-------------|------------|----------|
| `record` | One record at a time | Transformations, filtering |
| `file` | All records at once | Aggregation, deduplication |

### Record Granularity (Default)

```python
@udf_tool()
def filter_questions_by_score(data: dict, **kwargs) -> dict:
    score = data.get('syllabus_alignment_score', 0)
    if score >= 85:
        data['question_status'] = "KEEP"
    else:
        data['question_status'] = "FILTER"
    return data
```

### File Granularity

Use when your logic needs cross-record context:

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def run_dedup(data: list, **kwargs) -> list:
    seen = set()
    unique = []
    for record in data:
        fact = record.get('fact', '')
        if fact not in seen:
            seen.add(fact)
            unique.append(record)
    return unique
```

:::tip File Granularity is Tool-Only
File granularity is exclusively supported for tool actions. LLM actions must use record granularity.
:::

### File Granularity Constraints

- **Guards are not supported** - Implement filtering logic within your tool instead
- **Input is an array** - Your function receives the entire array of records
- **Output flexibility** - Return an array of any size (N→M transformation)

See [Granularity](../execution/granularity.md) for detailed documentation.

### Metadata is Automatic

The framework handles all metadata propagation (`source_guid`, lineage, `node_id`) automatically. Tools just return business data:

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def dedup_tool(data: list, **kwargs) -> list:
    seen = {}
    outputs = []

    for record in data:
        content = record.get("content", record)
        fact = content.get("fact", "")
        if fact not in seen:
            seen[fact] = True
            outputs.append(content)

    return outputs
```

The framework infers which inputs produced which outputs and propagates `source_guid` and lineage accordingly. Tools never need to handle framework metadata.

## Tool Discovery

Agent Actions automatically discovers tools decorated with `@udf_tool` from configured directories.

### Configuration

Set the tool path in `agent_actions.yml`:

```yaml
tool_path: ["tools", "custom_tools"]
```

Or use the `TOOLS_PATH` environment variable:

```bash
export TOOLS_PATH="tools"
```

### Directory Structure

```
project/
├── agent_actions.yml
├── tools/
│   ├── __init__.py          # Optional
│   ├── transformers.py      # Contains @udf_tool functions
│   └── validators.py
└── agent_workflow/
    └── ...
```

### Workflow Reference

Reference tools by function name:

```yaml
- name: flatten_the_facts
  kind: tool
  impl: flatten_quotes  # Function name (case-insensitive)
  granularity: record
```

### Discovery Process

1. Scans directories in `tool_path` recursively
2. Loads all Python files (`*.py`), skipping files starting with `_` or `test_`
3. Executes modules to trigger `@udf_tool` decorator registration
4. Validates `impl` references in agentic workflow config

:::info Thread Safety
Tool discovery is thread-safe and cached. Concurrent discovery calls are properly synchronized, and modules are loaded only once.
:::

## CLI Commands

```bash
# List all discovered tools
agac list-udfs -u ./tools

# Validate tool references in workflow
agac validate-udfs -a my_workflow -u ./tools
```

## Import Rules

Tool files are loaded in isolation using `importlib.util.spec_from_file_location`. The tools directory is **not** added to `sys.path`, so tools cannot import sibling modules with bare `import` statements.

What works:
- **Installed packages** — any dependency in your project's virtual environment (e.g., `import pandas`, `from agent_actions import udf_tool`)
- **Standard library** — `import json`, `import pathlib`, etc.

What does not work:
- **Sibling imports** — `import other_tool` or `from . import utils` where `other_tool` and `utils` are files in the same tools directory

If you need shared logic across multiple tool files, extract it into an installable package and add it to your project dependencies.

## Best Practices

### Handle Missing Fields

```python
@udf_tool()
def safe_function(data: dict, **kwargs) -> dict:
    score = data.get('score', 0)  # Use .get() with defaults
    return {'result': score}
```

### Return Complete Records

```python
@udf_tool()
def augment_data(data: dict, **kwargs) -> dict:
    data['new_field'] = 'computed_value'  # Add to existing, don't replace
    return data
```

### Unique Function Names

Tool names must be unique across all files. Prefix with domain if needed:

```python
@udf_tool()
def validate_email(data): ...

@udf_tool()
def validate_phone(data): ...
```

## Error Handling

### Duplicate Function Names

```
DuplicateFunctionError: Function 'process_data' already registered
  Existing: module_a.process_data (tools/module_a.py)
  New: module_b.process_data (tools/module_b.py)
```

Rename one of the functions.

### Function Not Found

```
FunctionNotFoundError: Function 'nonexistent_func' not found
```

Check that:
1. File is in `tools/` directory
2. Function has `@udf_tool` decorator
3. Function name matches workflow `impl`

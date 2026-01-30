---
title: Tool Actions
sidebar_position: 1
---

# Tool Actions

What happens when you need logic that an LLM can't perform? Deduplicating records, calling an external API, or applying deterministic business rules—these tasks need deterministic logic, not prompts.

Tool actions let you execute custom Python functions alongside LLM actions in your agentic workflow. When you need guaranteed, repeatable behavior, you use a tool.

## Quick Example

```python
from typing import TypedDict
from agent_actions import udf_tool

class MyOutput(TypedDict):
    result: str

@udf_tool(output_type=MyOutput)
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
| `output_type` | type | No | TypedDict, Pydantic model, or dataclass for output validation |
| `output_schema` | str | No | Schema file name for output validation (e.g., `"ValidationResult"`) |
| `granularity` | Granularity | No | `RECORD` (default) or `FILE` processing |

:::warning Mutually Exclusive
You cannot specify both `output_type` and `output_schema`. Use one or the other.
:::

:::info Input Schema
Input structure is defined by `context_scope` in your workflow YAML, not in the decorator. The decorator only handles output validation.
:::

### Minimal Decorator

```python
from agent_actions import udf_tool

@udf_tool()
def simple_transform(data: dict, **kwargs) -> dict:
    data['processed'] = True
    return data
```

## Output Type Definitions

### TypedDict (Recommended)

```python
from typing import TypedDict, Optional

class QuestionOutput(TypedDict, total=False):
    question_status: str
    status_reason: str
    processed_at: Optional[str]
```

The `total=False` makes all fields optional.

### Pydantic Model

```python
from pydantic import BaseModel

class QuestionOutput(BaseModel):
    question_status: str
    status_reason: str
```

### Dataclass

```python
from dataclasses import dataclass

@dataclass
class QuestionOutput:
    question_status: str
    status_reason: str
```

### External Schema File

```python
@udf_tool(output_schema="ValidationResult")
def validate_data(data: dict, **kwargs) -> dict:
    return {"valid": True, "errors": []}
```

## Granularity

| Granularity | Processing | Use Case |
|-------------|------------|----------|
| `record` | One record at a time | Transformations, filtering |
| `file` | All records at once | Aggregation, deduplication |

### Record Granularity (Default)

```python
@udf_tool(output_type=FilterOutput)
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

### FileUDFResult for Lineage

Track which input records produced which outputs:

```python
from agent_actions import udf_tool, FileUDFResult
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def dedup_with_lineage(data: list, **kwargs) -> FileUDFResult:
    seen = {}
    outputs = []
    source_mapping = {}

    for idx, record in enumerate(data):
        fact = record['fact']
        if fact not in seen:
            seen[fact] = len(outputs)
            outputs.append(record)
            source_mapping[len(outputs) - 1] = idx

    return FileUDFResult(
        outputs=outputs,
        source_mapping=source_mapping,
        input_count=len(data)
    )
```

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
agac list-tools -u ./tools

# Validate tool references in workflow
agac validate-tools -a my_workflow -u ./tools
```

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

### Both output_type and output_schema Specified

```
ConfigurationError: Cannot specify both output_schema and output_type for 'my_function'.
```

Choose one or the other.

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

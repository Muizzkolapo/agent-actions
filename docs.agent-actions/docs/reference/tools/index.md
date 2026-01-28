---
title: Tool Actions
sidebar_position: 1
---

# Tool Actions

What happens when you need logic that an LLM can't perform? Deduplicating records, calling an external API, or applying deterministic business rules—these tasks need code, not prompts.

Tool actions let you execute Python functions alongside LLM actions in your agentic workflow. Think of them as escape hatches: when you need guaranteed, repeatable behavior, you drop into Python.

## Overview

Tool actions provide:

- **Custom logic** - Implement transformations LLMs can't perform
- **Data processing** - Filter, transform, aggregate data
- **Integrations** - Connect to external services and APIs
- **Type safety** - Input/output validation via type hints

## Quick Example

```python
from typing import TypedDict
from agent_actions import udf_tool

class MyInput(TypedDict):
    text: str

@udf_tool(input_type=MyInput)
def process_text(data: dict) -> dict:
    return {"result": data["text"].upper()}
```

```yaml
- name: process_step
  kind: tool
  impl: process_text
  granularity: record
```

## Granularity

You might wonder: what if I need to see all records at once to deduplicate them? That's where granularity comes in.

| Granularity | Processing | Use Case |
|-------------|------------|----------|
| `record` | One record at a time | Transformations, filtering |
| `file` | All records at once | Aggregation, deduplication |

Record granularity is the default and works best for independent transformations. Use file granularity when your logic needs cross-record context.

:::tip File Granularity is Tool-Only
File granularity is exclusively supported for tool actions (`kind: tool`). LLM actions must use record granularity.

This makes sense: tools can efficiently process entire arrays in memory, while LLM actions need per-record prompt construction.
:::

### File Granularity Constraints

When using file granularity with tools:

1. **Guards are not supported** - Since file mode processes all records at once, per-record guards don't apply. Implement filtering logic within your UDF instead.

2. **Input is an array** - Your function receives the entire array of records, not a single record.

3. **Output flexibility** - Return an array of any size (N→M transformation), a single aggregated result, or even write to external files.

```yaml
# Valid: File granularity tool
- name: deduplicate_records
  kind: tool
  impl: deduplicate_by_hash
  granularity: file

# Invalid: Guard with file granularity
- name: conditional_dedupe
  kind: tool
  impl: deduplicate
  granularity: file
  guard:  # ERROR: Guards not supported with file granularity
    clause: "status == 'active'"
```

See [Granularity](../execution/granularity.md) for detailed documentation.

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

### Naming Conventions

| Config Field | Must Match |
|--------------|------------|
| `impl: function_name` | Function name decorated with `@udf_tool` |

```yaml
# Workflow config
- name: my_action
  kind: tool
  impl: process_data    # Must match function name
```

```python
# tools/transformers.py
@udf_tool(input_type=MyInput)
def process_data(data: dict) -> dict:  # Function name matches impl
    return {"result": data["value"]}
```

### Discovery Process

Let's walk through how Agent Actions finds your tools:

1. Scans directories in `tool_path` recursively
2. Loads all Python files (`*.py`), skipping files starting with `_` or `test_`
3. Executes modules to trigger `@udf_tool` decorator registration
4. Validates `impl` references in agentic workflow config

This means you can drop a new `.py` file in your tools directory, add the decorator, and it's immediately available—no registration step required.

### Thread Safety and Caching

Tool discovery is **thread-safe** and **cached**. This matters for batch processing where multiple jobs may run concurrently:

- **Thread-safe path management**: Concurrent tool discovery calls are properly synchronized
- **Path caching**: Directories are only added to `sys.path` once, preventing redundant insertions
- **Module caching**: Modules are loaded and executed only once, even if discovery is called multiple times

:::info Performance Note
For large tool directories, the first discovery call may be slower as it traverses the entire directory tree. Subsequent calls are fast due to caching.
:::

### CLI Commands

```bash
# List all discovered tools
agac list-udfs -u ./tools

# Validate tool references in workflow
agac validate-udfs -a my_workflow -u ./tools
```

### Best Practices

**1. One Tool Per File for Complex Logic**

```
tools/
├── flatten_quotes.py       # Single complex tool
├── merge_fields.py
└── validate_content.py
```

**2. Related Tools in Same File**

```python
# tools/validators.py
@udf_tool(input_type=EmailInput)
def validate_email(data): ...

@udf_tool(input_type=PhoneInput)
def validate_phone(data): ...
```

**3. Unique Function Names**

Tool names must be unique across all files. This is a limitation of the discovery system—there's no namespacing. If you have duplicates, Agent Actions catches this at startup:

```
ERROR: Duplicate function name 'process_data'
  First: tools/transformers.py
  Second: tools/helpers.py
```

## Learn More

- **[@udf_tool Decorator](./udf-decorator.md)** - Complete decorator documentation

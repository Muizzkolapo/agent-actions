# UDF Reference

Complete guide to writing Python UDF tool functions for agent-actions workflows.

## Table of Contents

- [@udf_tool Decorator](#udf_tool-decorator)
- [Directory Structure](#directory-structure)
- [Record Mode (Default)](#record-mode-default)
- [File Mode](#file-mode)
- [How Observed Fields Arrive](#how-observed-fields-arrive)
- [Passthrough Pattern](#passthrough-pattern)
- [Version Consumption Merge](#version-consumption-merge)
- [TypedDict for Nested Objects](#typeddict-for-nested-objects)
- [Type Mapping](#type-mapping)
- [Common Mistakes](#common-mistakes)
- [Best Practices](#best-practices)
- [Error Handling](#error-handling)
- [CLI Commands](#cli-commands)

## @udf_tool Decorator

Registers a Python function as a tool action:

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def my_function(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Process data and return result."""
    content = data.get("content", data)
    return [{"result": f"Processed: {content['text']}"}]
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `granularity` | Granularity | No | `RECORD` (default) or `FILE` |

The YAML config connects to this function via `impl`:

```yaml
- name: process_data
  kind: tool
  impl: my_function              # Function name (case-insensitive)
  granularity: record
```

## Directory Structure

```
project/
├── tools/
│   ├── __init__.py
│   ├── my_workflow/
│   │   ├── __init__.py
│   │   ├── transform_data.py
│   │   └── filter_records.py
│   └── shared/
│       ├── __init__.py
│       ├── utils.py
│       └── reprompt_validations.py
```

Function names must be unique across all tool directories. Move shared code to `tools/shared/`.

## Record Mode (Default)

UDF receives one record at a time. The framework unwraps the `content` wrapper before calling your function.

```python
@udf_tool()
def my_function(data: dict[str, Any]) -> list[dict[str, Any]]:
    content = data.get("content", data)  # Safety net — usually already unwrapped
    result = content.copy()
    result["computed_field"] = some_calculation(content)
    return [result]
```

**What `content` looks like:**

```json
{
  "extract_claims": {
    "claims": ["claim 1", "claim 2"],
    "confidence": 0.85
  },
  "seed": {
    "rubric": {"min_score": 7}
  }
}
```

| Input | Output |
|-------|--------|
| `dict` — business fields, already unwrapped | `list[dict]` (or `dict` with passthrough) |

## File Mode

UDF receives ALL records at once as a list. Unlike Record mode, the `content` wrapper is preserved — you must unwrap each item.

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def run_dedup(data: list[dict]) -> list[dict]:
    """FILE mode: each item has {"content": {...}, "source_guid": "..."}."""
    seen = {}
    outputs = []

    for record in data:
        content = record.get("content", record)  # Required — wrapper preserved
        fact = content.get("fact", "")
        if fact not in seen:
            seen[fact] = True
            outputs.append(content)

    return outputs
```

**What each item looks like:**

```json
{
  "content": {
    "extract_claims": {"claims": ["claim 1"], "confidence": 0.9}
  },
  "source_guid": "abc-123",
  "node_id": "node_2_xxx_0",
  "lineage": ["node_0_yyy", "node_1_zzz", "node_2_xxx_0"]
}
```

| Input | Output |
|-------|--------|
| `list[dict]` — each item retains `content` wrapper | `list[dict]` — business data only |

**Metadata is automatic.** FILE-mode tools return business data only — never handle `source_guid`, lineage, or `node_id`. The framework propagates metadata automatically based on input/output cardinality.

**Use FILE for:** Aggregation, deduplication, clustering, cross-record analysis.

## How Observed Fields Arrive

Observed fields arrive **namespaced by the action that produced them**. This is the #1 source of UDF bugs — flat access returns `None`.

### Standard observed fields (NAMESPACED)

```python
# CORRECT — namespaced access
title = content.get("write_marketing_copy", {}).get("listing_title", "")

# WRONG — flat access returns None
title = content.get("listing_title", "")  # None — field is under action namespace
```

When observing from a single upstream, unwrap the namespace upfront:

```python
upstream = content.get("write_marketing_copy", {})
title = upstream.get("listing_title", "")
description = upstream.get("listing_description", "")
```

### output_field values (json_mode: false)

With `json_mode: false` and `output_field`, the raw text lives under the action namespace:

```python
# Config: output_field: severity  (on action "assess_severity")
severity = content.get("assess_severity", {}).get("severity", "")

# Default output_field is "raw_response"
raw = content.get("action_name", {}).get("raw_response", "")
```

### Version consumption merge

After `version_consumption: {pattern: merge}`, versions are namespaced by expanded name:

```python
scorer_1 = content.get("score_quality_1", {}).get("overall_score")
scorer_2 = content.get("score_quality_2", {}).get("overall_score")

# Iterate dynamically
scores = []
for key, data in content.items():
    if key.startswith("score_quality_") and isinstance(data, dict):
        scores.append(data.get("overall_score", 0))
```

### Seed data

Seed data lives under the `seed` namespace:

```python
rules = content.get("seed", {}).get("marketplace_rules", {})
```

## Passthrough Pattern

When the YAML config uses `passthrough`, return a **dict** (not list) with only the new fields. The framework merges your new fields with the passthrough fields automatically.

```python
@udf_tool()
def inject_random_opener(data: dict) -> dict:
    """Return dict when using passthrough — only new fields."""
    content = data.get('content', data)
    quiz_type = content.get('quiz_type_used', 'general').lower()
    opener = random.choice(OPENERS.get(quiz_type, OPENERS['default']))
    return {"suggested_opener": opener, "quiz_type": quiz_type.upper()}
```

```yaml
- name: inject_opener
  kind: tool
  impl: inject_random_opener
  context_scope:
    observe: [upstream.quiz_type_used]
    passthrough: [upstream.*]          # Forward all upstream fields
```

## Version Consumption Merge

Process merged results from parallel versioned actions:

```python
@udf_tool()
def combine_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    content = data.get('content', data)
    results = []

    for i in range(1, 4):  # versions 1-3
        worker_key = f'score_quality_{i}'
        worker_data = content.get(worker_key, {})
        if isinstance(worker_data, dict):
            results.append({
                'version': i,
                'score': worker_data.get('score', 0),
                'reasoning': worker_data.get('reasoning', ''),
            })

    avg_score = sum(r['score'] for r in results) / len(results) if results else 0
    return [{'all_scores': results, 'average_score': avg_score}]
```

## TypedDict for Nested Objects

When your UDF returns nested objects, use nested `TypedDict` classes — not `dict[str, Any]`. The framework converts `dict[str, Any]` to `additionalProperties: {type: string}`, forcing all values to strings.

```python
# BAD — schema validation errors (all values forced to string)
class MyOutput(TypedDict, total=False):
    metadata: dict[str, Any]           # int/float become strings

# GOOD — types preserved correctly
class SearchMetadata(TypedDict, total=False):
    total_count: int
    method: str

class MatchingItem(TypedDict, total=False):
    id: str
    score: float

class MyOutput(TypedDict, total=False):
    results: list[MatchingItem]
    metadata: SearchMetadata
```

## Type Mapping

| JSON Schema | Python | Notes |
|-------------|--------|-------|
| string | `str` | |
| integer | `int` | |
| number | `float` | |
| array | `list[str]` or `list[Any]` | |
| object | `dict` | Use TypedDict for nested |
| varies | `Any` | |

## Common Mistakes

```python
# WRONG: Forgot content wrapper
def bad_udf(data):
    return [{'result': data['field']}]  # KeyError if wrapped

# WRONG: Returned dict instead of list (without passthrough)
def bad_udf(data):
    return {'result': 'value'}  # Must be [{'result': 'value'}]

# WRONG: Flat access for observed fields
def bad_udf(data):
    content = data.get("content", data)
    result = content.get("field")  # None — field is under action namespace
    # CORRECT: result = content.get("upstream_action", {}).get("field")

# WRONG: Default doesn't match schema type
def bad_udf(data):
    return [{"name": None}]  # schema says type: string → validation error
    # CORRECT: return [{"name": ""}]

# WRONG: FILE mode forgetting to unwrap content
def bad_udf(data):
    for record in data:
        fact = record.get("fact")  # None — fact is inside "content"
    # CORRECT: fact = record.get("content", record).get("fact")
```

## Best Practices

- Always use `data.get("content", data)` as the first line — handles both wrapped and unwrapped cases
- Use `.get()` with defaults for all field access: `content.get("score", 0)` prevents `KeyError`
- Return complete records — prefer `content.copy()` + add fields over building from scratch
- Use descriptive TypedDict names (`QuestionQualityInput`, not `Input1`)
- Document expected input/output in the docstring

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `DuplicateFunctionError: Function 'X' already registered` | Same name in multiple files | Rename or move to `tools/shared/` |
| `FunctionNotFoundError: Function 'X' not found` | File not in `tools/`, missing decorator, or name mismatch | Check path, `@udf_tool()`, and `impl:` |
| `TypeError: expected list, got dict` | Returned dict without passthrough | Return `[result]` or add passthrough to YAML |

## CLI Commands

```bash
# List registered UDFs
agac list-udfs -u <tools_path>
agac list-udfs -u <tools_path> --json      # JSON output
agac list-udfs -u <tools_path> --verbose   # Full signatures

# Validate UDF references match config
agac validate-udfs -a <workflow> -u <tools_path>
```

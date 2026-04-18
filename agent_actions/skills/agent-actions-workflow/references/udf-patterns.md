# UDF Patterns Reference

Python UDF patterns for agent-actions workflows.

## Record vs File: What Your UDF Receives

The framework passes different data structures depending on granularity:

| | Record (default) | File |
|---|---|---|
| **Input** | `dict` — business fields only, already unwrapped | `list[dict]` — each item has `{"content": {...}, "source_guid": "..."}` |
| **Content wrapper** | Stripped by framework | Preserved — you must unwrap each item |
| **Return type** | `list[dict]` (or `dict` with passthrough) | `FileUDFResult` |

## Record Template

In Record mode, the framework unwraps the content before calling your function. The `.get("content", data)` is a safety net but the data is already flat:

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def my_function(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Process one record at a time."""
    content = data.get("content", data)  # Safety net — usually already unwrapped
    result = content.copy()
    result["computed_field"] = some_calculation(content)
    return [result]
```

## Passthrough Pattern

When using `passthrough` in the YAML config, return a **dict** (not list) with only the new fields:

```python
@udf_tool()
def inject_random_opener(data: dict) -> dict:
    """Inject computed content. Return dict when using passthrough."""
    content = data.get('content', data)
    quiz_type = content.get('quiz_type_used', 'general').lower()
    opener = random.choice(OPENERS.get(quiz_type, OPENERS['default']))
    return {"suggested_opener": opener, "quiz_type": quiz_type.upper()}
```

## Version Consumption Merge

Process merged results from parallel versioned actions:

```python
@udf_tool()
def process_merged(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge outputs from versioned actions."""
    content = data.get('content', data)
    results = []

    for i in range(1, 6):
        worker_key = f'process_data_{i}'
        worker_data = content.get(worker_key, {})
        if isinstance(worker_data, dict):
            results.append({
                'worker_id': i,
                'result': worker_data.get('result'),
                'score': worker_data.get('score', 0),
            })

    output = content.copy()
    output['all_results'] = results
    output['average_score'] = (
        sum(r['score'] for r in results) / len(results) if results else 0
    )
    return [output]
```

## FILE Granularity

Receives ALL records at once as a list. Unlike Record mode, the content wrapper is **preserved** — you must unwrap each item with `.get("content", record)`. Preserve `source_guid` for lineage:

```python
from agent_actions import udf_tool, FileUDFResult
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def run_dedup(data: list[dict]) -> FileUDFResult:
    """FILE mode: each item still has {"content": {...}, "source_guid": "..."}."""
    seen = {}
    outputs = []

    for record in data:
        content = record.get("content", record)  # ← Required here: wrapper preserved
        fact = content.get("fact", "")
        if fact not in seen:
            seen[fact] = True
            outputs.append({
                **content,
                "source_guid": record.get("source_guid"),
            })

    return FileUDFResult(outputs=outputs, input_count=len(data))
```

## How Observed Fields Arrive in UDFs

Observed fields arrive **namespaced by action name**. Access them as `content.get("action_name", {}).get("field")`.

### 1. Standard observed fields (NAMESPACED)

Observed fields are nested under the action name that produced them. This preserves data integrity when multiple upstream actions share field names.

```python
# CORRECT — namespaced access
title = content.get("write_marketing_copy", {}).get("listing_title", "")

# WRONG — flat access returns None (fields are namespaced)
title = content.get("listing_title", "")  # None — field is under action namespace
```

When observing from a single upstream action, you can unwrap the namespace upfront:

```python
upstream = content.get("write_marketing_copy", {})
title = upstream.get("listing_title", "")
description = upstream.get("listing_description", "")
```

### 2. `output_field` values (under the ACTION namespace)

With `json_mode: false` and `output_field`, the raw text is stored under the `output_field` name within the action namespace.

```python
# Config: output_field: severity  (on action "assess_severity")

# CORRECT — action namespace, then field name
severity = content.get("assess_severity", {}).get("severity", "")

# WRONG — flat access
severity = content.get("severity", "")  # None
```

**Note:** The default `output_field` is `raw_response`. Access via `content.get("action_name", {}).get("raw_response", "")`.

### 3. Version consumption merge (NAMESPACED under expanded names)

Versioned data is nested under expanded action names. Each version's data is preserved independently — no data loss from field name collisions.

```python
scorer_1 = content.get("score_quality_1", {}).get("overall_score")
scorer_2 = content.get("score_quality_2", {}).get("overall_score")
scorer_3 = content.get("score_quality_3", {}).get("overall_score")

# Iterate all versions dynamically
scores = []
for key, data in content.items():
    if key.startswith("score_quality_") and isinstance(data, dict):
        scores.append(data.get("overall_score", 0))
```

### 4. Seed data (under `seed` namespace)

Seed data observed as `seed.marketplace_rules` arrives under `content["seed"]["marketplace_rules"]`.

```python
rules = content.get("seed", {}).get("marketplace_rules", {})
```

## Common Mistakes

```python
# WRONG: Forgot content wrapper
def bad_udf(data):
    return [{'result': data['field']}]  # KeyError if wrapped

# WRONG: Returned dict instead of list (without passthrough)
def bad_udf(data):
    return {'result': 'value'}  # Must be [{'result': 'value'}]

# WRONG: Flat access for observed fields (fields are namespaced)
def bad_udf(data):
    content = data.get("content", data)
    result = content.get("field")  # None — field is under action namespace
    # CORRECT: result = content.get("upstream_action", {}).get("field")

# WRONG: Default doesn't match schema type
def bad_udf(data):
    return [{"name": None}]  # schema says type: string → validation error
    # CORRECT: return [{"name": ""}]
```

## Type Mapping

| JSON | Python |
|------|--------|
| string | `str` |
| integer | `int` |
| number | `float` |
| array | `list[str]` or `list[Any]` |
| object | `dict` |
| varies | `Any` |

## TypedDict Note

When your UDF returns nested objects, use nested `TypedDict` classes instead of `dict[str, Any]`. The framework converts `dict[str, Any]` to `additionalProperties: {type: string}`, which forces all values to strings and causes schema validation errors.

```python
# BAD
class MyOutput(TypedDict, total=False):
    metadata: dict[str, Any]       # All values forced to string

# GOOD
class SearchMetadata(TypedDict, total=False):
    total_count: int
    method: str

class MyOutput(TypedDict, total=False):
    metadata: SearchMetadata       # Types preserved
```

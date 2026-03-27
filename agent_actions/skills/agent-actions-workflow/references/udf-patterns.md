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

## Common Mistakes

```python
# WRONG: Forgot content wrapper
def bad_udf(data):
    return [{'result': data['field']}]  # KeyError if wrapped

# WRONG: Returned dict instead of list (without passthrough)
def bad_udf(data):
    return {'result': 'value'}  # Must be [{'result': 'value'}]
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

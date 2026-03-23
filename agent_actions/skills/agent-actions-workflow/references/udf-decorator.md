# @udf_tool Decorator Reference

The `@udf_tool` decorator registers Python functions as tool actions in workflows.

## Syntax

```python
from agent_actions import udf_tool

@udf_tool()
def my_function(data: dict) -> dict:
    """Process data and return result."""
    return {"result": f"Processed: {data['text']}"}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `granularity` | Granularity | No | `RECORD` (default) or `FILE` |

Input and output schemas are defined via the YAML `schema:` field in the workflow configuration, not in the decorator.

## Directory Structure

```
project/
├── agent_actions.yml
├── tools/
│   ├── __init__.py
│   ├── my_workflow/
│   │   ├── __init__.py
│   │   ├── transform_data.py
│   │   └── filter_records.py
│   └── shared/
│       └── utils.py
```

## Workflow Reference

```yaml
- name: flatten_the_facts
  kind: tool
  impl: flatten_quotes  # Function name (case-insensitive)
  granularity: record
```

## Granularity

### Record (Default)

Process one record at a time:

```python
@udf_tool()
def filter_questions_by_score(data: dict) -> dict:
    content = data.get('content', data)
    score = content.get('syllabus_alignment_score', 0)
    result = content.copy()
    if score >= 85:
        result['question_status'] = "KEEP"
    else:
        result['question_status'] = "FILTER"
    return result
```

```yaml
- name: filter_low_quality_questions
  kind: tool
  impl: filter_questions_by_score
  granularity: record
```

### File

Process all records at once:

```python
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def run_dedup(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for record in data:
        fact = record.get('fact', '')
        if fact not in seen:
            seen.add(fact)
            unique.append(record)
    return unique
```

```yaml
- name: cluster_list
  kind: tool
  impl: run_dedup
  granularity: file
```

Use FILE for: Aggregation, deduplication, clustering, cross-record analysis.

## FileUDFResult for FILE-Mode Tools

`FileUDFResult` wraps FILE-mode output with optional metadata. The runtime
unwraps it to `.outputs` before structuring records.

**Important:** Lineage is tracked via `source_guid`, not `source_mapping`.
The pipeline's FILE-mode handler preserves `source_guid` on each output item
and `LineageEnricher` resolves ancestry from it. `source_mapping` is validated
at construction time but is **not yet consumed** by the runtime for lineage
resolution. Always copy `source_guid` from inputs to outputs for correct
lineage.

```python
from agent_actions import FileUDFResult

@udf_tool(granularity=Granularity.FILE)
def dedup_with_lineage(data: list[dict]) -> FileUDFResult:
    seen = {}
    outputs = []

    for record in data:
        fact = record.get("content", record).get("fact", "")
        if fact not in seen:
            seen[fact] = True
            # Preserve source_guid so the framework can resolve lineage
            outputs.append({
                **record.get("content", record),
                "source_guid": record.get("source_guid"),
            })

    return FileUDFResult(
        outputs=outputs,
        input_count=len(data),
    )
```

## Nested TypedDicts for Complex Output

When your UDF returns nested objects, use nested `TypedDict` classes instead of `dict[str, Any]`. The framework converts `dict[str, Any]` to `additionalProperties: {type: string}`, causing schema validation errors.

```python
# BAD - schema validation errors (all values forced to string)
class MyOutput(TypedDict, total=False):
    results: list[dict[str, Any]]
    metadata: dict[str, Any]

# GOOD - explicit nested types preserve int/float/etc.
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

## Best Practices

- **Use `.get()` with defaults** for all field access: `data.get('score', 0)` prevents `KeyError` on missing fields.
- **Document expected input/output** in the docstring so downstream consumers know what fields to expect.
- **Use descriptive TypedDict names** (`QuestionQualityInput`, not `Input1`) when using typed schemas.
- **Return complete records** -- prefer `content.copy()` + add fields over building from scratch, so downstream actions retain all upstream data.

## Error Handling

**Duplicate Function Names:**
```
DuplicateFunctionError: Function 'process_data' already registered
```
Function names must be unique across all tool files.

**Function Not Found:**
```
FunctionNotFoundError: Function 'nonexistent_func' not found
```
Check file is in `tools/`, imported, and function name matches `impl`.

## CLI Commands

```bash
# List registered UDFs
agac list-udfs -u <tools_path>

# Validate UDF schemas
agac validate-udfs -a <workflow_name> -u <tools_path>
```

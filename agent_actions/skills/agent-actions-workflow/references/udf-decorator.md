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
    score = data.get('syllabus_alignment_score', 0)
    if score >= 85:
        data['question_status'] = "KEEP"
    else:
        data['question_status'] = "FILTER"
    return data
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
from agent_actions.configuration.new_format_schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def run_dedup(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

## FileUDFResult for Lineage

Track which inputs produced which outputs:

```python
from agent_actions.utilities.udf_management.udf_registry import FileUDFResult

@udf_tool(granularity=Granularity.FILE)
def dedup_with_lineage(data: List[Dict]) -> FileUDFResult:
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

## Nested TypedDicts for Complex Output

When your UDF returns nested objects, **always use nested TypedDicts** instead of `Dict[str, Any]`. The framework converts `Dict[str, Any]` incorrectly to `additionalProperties: {type: string}`, causing schema validation errors.

### Problem: Dict[str, Any]

```python
# BAD - Will cause schema validation errors
class MyOutput(TypedDict, total=False):
    results: List[Dict[str, Any]]      # Converted to additionalProperties: {type: 'string'}
    metadata: Dict[str, Any]           # All values must be strings!
```

### Solution: Nested TypedDicts

```python
# GOOD - Explicit types for nested structures
class SearchMetadata(TypedDict, total=False):
    """Metadata about the search operation."""
    total_count: int           # int type preserved
    results_returned: int      # int type preserved
    search_method: str
    filters_applied: List[str]

class MatchingItem(TypedDict, total=False):
    """A single matching item."""
    id: str
    title: str
    score: float               # float type preserved
    tags: List[str]

class MyOutput(TypedDict, total=False):
    """Output schema with proper nested types."""
    results: List[MatchingItem]
    metadata: SearchMetadata
```

### Complete Example

```python
from typing import TypedDict, List
from agent_actions import udf_tool

class OperationMetadata(TypedDict, total=False):
    total_processed: int
    matches_found: int
    method: str

class ResultItem(TypedDict, total=False):
    id: str
    name: str
    score: float

class SearchInput(TypedDict, total=False):
    query: str
    filters: List[str]

@udf_tool()
def search_items(data: dict) -> dict:
    return {
        "results": [
            {"id": "123", "name": "Item A", "score": 0.95}
        ],
        "metadata": {
            "total_processed": 100,      # int works correctly
            "matches_found": 15,          # int works correctly
            "method": "fuzzy_match"
        }
    }
```

## Best Practices

### 1. Use Descriptive Type Names

```python
# Good
class QuestionQualityInput(TypedDict):
    score: int
    question: str

# Avoid
class Input1(TypedDict):
    x: int
```

### 2. Document Expected Input

```python
@udf_tool()
def my_function(data: dict) -> dict:
    """
    Process data for downstream consumption.

    Expected input fields:
        - score: Quality score (0-100)
        - text: Content to process

    Output:
        - status: "KEEP" or "FILTER"
        - reason: Explanation
    """
```

### 3. Handle Missing Fields

```python
@udf_tool()
def safe_function(data: dict) -> dict:
    score = data.get('score', 0)  # Use .get() with defaults
    text = data.get('text', '')
    return {'result': f"{score}: {text}"}
```

### 4. Return Complete Records

```python
@udf_tool()
def augment_data(data: dict) -> dict:
    data['new_field'] = 'computed_value'  # Add, don't replace
    return data
```

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
agac list-udfs

# Validate UDF schemas
agac validate --udfs
```

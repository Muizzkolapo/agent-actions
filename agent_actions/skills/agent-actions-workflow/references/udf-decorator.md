# @udf_tool Decorator Reference

The `@udf_tool` decorator registers Python functions as tool actions in workflows.

## Syntax

### New Style (Recommended)

UDFs now work like LLM actions: `context_scope` in the workflow YAML defines input, `schema` or `output_schema` defines output.

```python
from agent_actions import udf_tool

@udf_tool(output_schema="MyOutputSchema")
def my_function(data: dict) -> dict:
    """Process data and return result."""
    return {"result": f"Processed: {data['text']}"}
```

```yaml
# Workflow YAML
- name: process_data
  kind: tool
  impl: my_function
  schema: MyOutputSchema  # Output validation
  context_scope:
    include:
      - upstream_action.text
      - upstream_action.count
```

### Legacy Style (Deprecated)

The old style with `input_type` is still supported but deprecated:

```python
from typing import TypedDict
from agent_actions import udf_tool

class MyInput(TypedDict):
    text: str
    count: int

class MyOutput(TypedDict):
    result: str

@udf_tool(input_type=MyInput, output_type=MyOutput)
def my_function(data: dict) -> dict:
    """Process data and return result."""
    return {"result": f"Processed: {data['text']}"}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `output_schema` | str | No | Schema file name for output validation (new style) |
| `input_type` | type | No | TypedDict, Pydantic model, or dataclass (deprecated) |
| `output_type` | type | No | Type for output validation (deprecated) |
| `granularity` | Granularity | No | `RECORD` (default) or `FILE` |

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

## New Style UDFs

The new style eliminates the "triple definition problem" where input structure was specified in three places: `context_scope`, type annotations, AND the decorator.

### Simple UDF

```python
from agent_actions import udf_tool

@udf_tool()
def filter_questions_by_score(data: dict) -> dict:
    """Input fields come from context_scope in workflow YAML."""
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
  context_scope:
    include:
      - extract_questions.syllabus_alignment_score
      - extract_questions.question
```

### UDF with Output Schema

```python
@udf_tool(output_schema="ValidationResult")
def validate_data(data: dict) -> dict:
    """Output validated against ValidationResult schema."""
    return {
        "valid": True,
        "errors": []
    }
```

## Legacy Input Type Definition

These patterns are still supported but deprecated.

### TypedDict

```python
from typing import TypedDict, List, Optional

class QuestionInput(TypedDict, total=False):
    """Input schema for question processing."""
    syllabus_alignment_score: int
    question: str
    options: List[str]
    answer: str
    reasoning: Optional[str]

@udf_tool(input_type=QuestionInput)
def process(data: dict) -> dict:
    ...
```

`total=False` makes all fields optional.

### Pydantic Model

```python
from pydantic import BaseModel
from typing import List

class QuestionInput(BaseModel):
    question: str
    options: List[str]
    answer: str

@udf_tool(input_type=QuestionInput)
def process(data: dict) -> dict:
    ...
```

### Dataclass

```python
from dataclasses import dataclass
from typing import List

@dataclass
class QuestionInput:
    question: str
    options: List[str]
    answer: str

@udf_tool(input_type=QuestionInput)
def process(data: dict) -> dict:
    ...
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

**Constraints:**
- FILE granularity only works with `kind: tool` (not LLM actions)
- Guards are not supported with FILE granularity

## Data Format: RECORD vs FILE

### RECORD Mode Input

Your UDF receives **one record at a time**:

```python
# Input to your UDF (single dict)
{
    "question": "What is MCP?",
    "answer": "A protocol",
    "source_guid": "abc-123",
    "target_id": "xyz-456",
    "node_id": "extract_qa_0",
    "lineage": ["extract_qa_0"]
}
```

### FILE Mode Input

Your UDF receives **the entire array**:

```python
# Input to your UDF (list of dicts)
[
    {
        "question": "What is MCP?",
        "answer": "A protocol",
        "source_guid": "abc-123",
        "target_id": "xyz-456",
        "node_id": "extract_qa_0",
        "lineage": ["extract_qa_0"]
    },
    {
        "question": "How does it work?",
        "answer": "Via messages",
        "source_guid": "abc-123",
        "target_id": "xyz-789",
        "node_id": "extract_qa_1",
        "lineage": ["extract_qa_1"]
    }
]
```

### Metadata Wrapping in FILE Mode

The framework automatically wraps your FILE mode output with metadata. Your UDF returns raw data, and the framework adds:

- **`content`** - Your data wrapped in a content field
- **`source_guid`** - Preserved from input if you copy it to output
- **`target_id`** - New unique identifier assigned to each output
- **`node_id`** - Identifies which action produced the output
- **`lineage`** - Array tracking the processing chain
- **`metadata`** - Provider and model information

**Your UDF returns:**
```python
[
    {"source_guid": "abc-123", "question": "What is MCP?", "answer": "A protocol"},
    {"source_guid": "abc-123", "question": "How does it work?", "answer": "Via messages"}
]
```

**Framework wraps it as:**
```json
[
    {
        "source_guid": "abc-123",
        "content": {"question": "What is MCP?", "answer": "A protocol"},
        "target_id": "new-uuid-1",
        "node_id": "flatten_questions_xyz_0",
        "lineage": ["extract_qa_previous", "flatten_questions_xyz_0"],
        "metadata": {"model": "flatten_questions", "provider": "tool"}
    },
    {
        "source_guid": "abc-123",
        "content": {"question": "How does it work?", "answer": "Via messages"},
        "target_id": "new-uuid-2",
        "node_id": "flatten_questions_xyz_1",
        "lineage": ["extract_qa_previous", "flatten_questions_xyz_1"],
        "metadata": {"model": "flatten_questions", "provider": "tool"}
    }
]
```

**Important:** To maintain lineage chaining, copy the `source_guid` from input records to your output. The framework uses this to look up the parent record and chain lineage correctly.

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

class SearchOutput(TypedDict, total=False):
    results: List[ResultItem]
    metadata: OperationMetadata

@udf_tool(output_schema="SearchOutput")
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

### 1. Use New Style UDFs

```python
# Recommended - input from context_scope, output from schema
@udf_tool(output_schema="MyOutput")
def process(data: dict) -> dict:
    ...
```

### 2. Use Descriptive Type Names (Legacy)

```python
# Good
class QuestionQualityInput(TypedDict):
    score: int
    question: str

# Avoid
class Input1(TypedDict):
    x: int
```

### 3. Document Expected Input

```python
@udf_tool()
def my_function(data: dict) -> dict:
    """
    Process data for downstream consumption.

    Expected input fields (from context_scope):
        - score: Quality score (0-100)
        - text: Content to process

    Output:
        - status: "KEEP" or "FILTER"
        - reason: Explanation
    """
```

### 4. Handle Missing Fields

```python
@udf_tool()
def safe_function(data: dict) -> dict:
    score = data.get('score', 0)  # Use .get() with defaults
    text = data.get('text', '')
    return {'result': f"{score}: {text}"}
```

### 5. Return Complete Records

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

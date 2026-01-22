---
title: "@udf_tool Decorator"
sidebar_position: 1
---

# @udf_tool Decorator

How do you tell Agent Actions that a Python function should be available as a tool action? The `@udf_tool` decorator handles this registration, along with input/output schema validation.

UDFs (User-Defined Functions) let you add custom data processing, transformations, and business logic to your agentic workflows. The decorator ensures your functions integrate cleanly with the rest of the execution pipeline.

## Overview

UDFs provide:

- **Custom logic** - Implement transformations LLMs can't perform
- **Type safety** - Input/output schema validation via type hints
- **Integration** - Seamlessly mix with LLM actions in workflows
- **Granularity control** - Process records individually or in batches

## Syntax

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
| `input_type` | type | Yes | TypedDict, Pydantic model, or dataclass for input schema |
| `output_type` | type | No | Type for output validation |
| `granularity` | Granularity | No | `RECORD` (default) or `FILE` processing |

## Directory Structure

UDFs are placed in the `tools/` directory:

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
└── agent_workflow/
    └── ...
```

## Agentic Workflow Reference

Reference UDFs in your agentic workflow YAML by function name:

```yaml
- name: flatten_the_facts
  kind: tool
  impl: flatten_quotes  # Function name (case-insensitive)
  granularity: record
```

## Input Type Definition

### TypedDict (Recommended)

TypedDict works like a schema definition—it tells Agent Actions what fields to expect:

```python
from typing import TypedDict, List, Optional

class QuestionInput(TypedDict, total=False):
    """Input schema for question processing."""
    syllabus_alignment_score: int
    question: str
    options: List[str]
    answer: str
    reasoning: Optional[str]
```

The `total=False` makes all fields optional, which is useful when different records might have different fields present.

### Pydantic Model

```python
from pydantic import BaseModel
from typing import List

class QuestionInput(BaseModel):
    question: str
    options: List[str]
    answer: str
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
```

## Examples

### Record-Level Processing (Default)

Let's explore a typical use case: processing one record at a time to add computed fields:

```python
from typing import TypedDict, List
from agent_actions import udf_tool


class FilterInput(TypedDict, total=False):
    syllabus_alignment_score: int
    question: str
    options: List[str]


@udf_tool(input_type=FilterInput)
def filter_questions_by_score(data: dict) -> dict:
    """
    Mark questions based on alignment score.

    Adds question_status: "KEEP" or "FILTER"
    """
    score = data.get('syllabus_alignment_score', 0)
    THRESHOLD = 85

    if score >= THRESHOLD:
        data['question_status'] = "KEEP"
        data['status_reason'] = f"Score {score} meets threshold"
    else:
        data['question_status'] = "FILTER"
        data['status_reason'] = f"Score {score} below threshold"

    return data
```

Workflow usage:

```yaml
- name: filter_low_quality_questions
  kind: tool
  impl: filter_questions_by_score
  granularity: record
```

### File-Level Processing (Batch)

Consider what happens when you need to deduplicate facts across all records. You can't do this record-by-record—you need to see everything at once:

```python
from typing import TypedDict, List, Dict, Any
from agent_actions import udf_tool
from agent_actions.configuration.new_format_schema import Granularity


class FactInput(TypedDict, total=False):
    fact: str
    quote: str


@udf_tool(input_type=FactInput, granularity=Granularity.FILE)
def run_dedup(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate facts across all records.

    FILE granularity receives entire array of records.
    """
    seen = set()
    unique = []

    for record in data:
        fact = record.get('fact', '')
        if fact not in seen:
            seen.add(fact)
            unique.append(record)

    return unique
```

Workflow usage:

```yaml
- name: cluster_list
  kind: tool
  impl: run_dedup
  granularity: file
```

### Data Transformation

```python
from typing import TypedDict, List, Dict, Any
from agent_actions import udf_tool


class FlattenInput(TypedDict, total=False):
    candidate_facts_list: List[dict]


@udf_tool(input_type=FlattenInput)
def flatten_quotes(data: dict) -> List[Dict[str, Any]]:
    """
    Flatten nested facts structure.

    Extracts facts from candidate_facts_list and merges
    with shared parent fields.
    """
    facts = data.get('candidate_facts_list', [])
    shared_keys = {k: v for k, v in data.items()
                   if k != 'candidate_facts_list'}

    flattened = []
    for fact in facts:
        flattened.append({**shared_keys, **fact})

    return flattened
```

### Output Type Validation

```python
from typing import TypedDict
from agent_actions import udf_tool


class ProcessInput(TypedDict):
    text: str


class ProcessOutput(TypedDict):
    processed: str
    word_count: int


@udf_tool(input_type=ProcessInput, output_type=ProcessOutput)
def process_text(data: dict) -> dict:
    """Process text with validated output."""
    text = data['text']
    return {
        'processed': text.upper(),
        'word_count': len(text.split())
    }
```

## Granularity

Think of granularity as the "zoom level" of your function. Do you want to see one record at a time, or the whole file?

### Record (Default)

- Function called once per record
- Input: Single dict
- Output: Single dict or list of dicts
- Best for: Transformations, filtering, computed fields

```yaml
- name: my_tool
  kind: tool
  impl: my_function
  granularity: record  # Default
```

### File

- Function called once with all records
- Input: List of dicts
- Output: List of dicts
- Best for: Aggregation, deduplication, clustering

```yaml
- name: cluster_facts
  kind: tool
  impl: cluster_function
  granularity: file
```

The tradeoff: file granularity gives you more context but requires all records to fit in memory. For very large datasets, prefer record granularity with external storage for cross-record state.

## FileUDFResult for Lineage

Here's where it gets interesting: with file granularity, how do you track which input records produced which outputs? If you deduplicate 100 records down to 50, Agent Actions needs to know the mapping for lineage tracking.

Use `FileUDFResult` to track which inputs produced which outputs:

```python
from typing import TypedDict, List, Dict
from agent_actions import udf_tool
from agent_actions.utilities.udf_management.udf_registry import FileUDFResult
from agent_actions.configuration.new_format_schema import Granularity


class DedupInput(TypedDict):
    fact: str
    id: str


@udf_tool(input_type=DedupInput, granularity=Granularity.FILE)
def dedup_with_lineage(data: List[Dict]) -> FileUDFResult:
    """Deduplicate with source tracking."""
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

## Function Discovery

UDFs are auto-discovered from the `tools/` directory. The function name (case-insensitive) is used for workflow reference:

```python
# tools/my_tools/process.py
@udf_tool(input_type=MyInput)
def process_data(data):  # Referenced as "process_data"
    ...
```

```yaml
- name: process_step
  kind: tool
  impl: process_data  # Matches function name
```

## Best Practices

### 1. Use Descriptive Type Names

```python
# Good: Clear purpose
class QuestionQualityInput(TypedDict):
    score: int
    question: str

# Avoid: Vague names
class Input1(TypedDict):
    x: int
```

### 2. Document Expected Input

```python
@udf_tool(input_type=MyInput)
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

### 3. Handle Missing Fields Gracefully

```python
@udf_tool(input_type=MyInput)
def safe_function(data: dict) -> dict:
    # Use .get() with defaults
    score = data.get('score', 0)
    text = data.get('text', '')

    return {'result': f"{score}: {text}"}
```

### 4. Return Complete Records

```python
@udf_tool(input_type=MyInput)
def augment_data(data: dict) -> dict:
    # Add to existing data, don't replace
    data['new_field'] = 'computed_value'
    return data
```

### 5. Use Logging for Debugging

```python
@udf_tool(input_type=MyInput)
def debuggable_function(data: dict) -> dict:
    print(f"Processing record: {data.get('id', 'unknown')}")
    result = process(data)
    print(f"Result: {result.get('status')}")
    return result
```

## Error Handling

Agent Actions catches configuration problems early. Here are common errors and how to fix them.

### Missing Input Type

```
ConfigurationError: udf_tool requires input_type parameter.
  Use @udf_tool(input_type=MyType)
```

The input_type parameter is required—it's how Agent Actions validates incoming data:

```python
# Wrong
@udf_tool
def my_function(data):
    ...

# Correct
@udf_tool(input_type=MyInput)
def my_function(data):
    ...
```

### Duplicate Function Names

```
DuplicateFunctionError: Function 'process_data' already registered
  Existing: module_a.process_data (tools/module_a.py)
  New: module_b.process_data (tools/module_b.py)
```

Function names must be unique across all tool files. This is a limitation of the current discovery system—consider prefixing function names with their domain (e.g., `validate_email` vs `validate_phone`).

### Function Not Found

```
FunctionNotFoundError: Function 'nonexistent_func' not found
  Available: process_data, filter_records, flatten_quotes
```

Check that:
1. File is in `tools/` directory
2. File is imported (check `__init__.py`)
3. Function name matches workflow `impl`

## CLI Commands

List registered UDFs:

```bash
agac list-udfs
```

Validate UDF schemas:

```bash
agac validate --udfs
```

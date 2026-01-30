# UDF Patterns Reference

Python UDF patterns for agent-actions workflows.

## Essential UDF Template

**CRITICAL: Always handle content wrapper and return a list.**

```python
from typing import Any, Dict, List
from agent_actions import udf_tool

@udf_tool()
def my_function(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Process data and return modified dict."""
    # STEP 1: Handle content wrapper (REQUIRED)
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # STEP 2: Process data
    computed_value = some_calculation(content)

    # STEP 3: Forward ALL fields + add computed (RECOMMENDED)
    result = content.copy()
    result['computed_field'] = computed_value

    # STEP 4: Return as LIST (REQUIRED)
    return [result]
```

## Content Wrapper Helper

```python
def unwrap(data: dict) -> dict:
    """Extract content from wrapper if present."""
    return data.get('content', data) if isinstance(data, dict) else data

@udf_tool()
def my_udf(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    content = unwrap(data)
    result = content.copy()
    result['computed'] = some_calculation(content)
    return [result]
```

## Field Forwarding Patterns

### Option A: Forward ALL fields (Recommended)
```python
result = content.copy()
result['new_field'] = computed_value
return [result]
```

### Option B: Forward specific fields only
```python
result = {
    'computed_field': some_calculation(),
    'field1': content.get('field1'),
    'field2': content.get('field2')
}
return [result]
```

### Option C: Return only computed fields
```python
# Downstream accesses other fields via lineage
result = {'computed_field': some_calculation()}
return [result]
```

## Common Mistakes

```python
# WRONG: Forgot content wrapper
def bad_udf(data):
    return [{'result': data['field']}]  # KeyError if wrapped

# WRONG: Returned dict instead of list
def bad_udf(data):
    return {'result': 'value'}  # Must be [{'result': 'value'}]
```

## Content Injection Pattern (with Passthrough)

For injecting computed/randomized content while forwarding upstream fields:

**YAML config:**
```yaml
- name: inject_opener
  dependencies: [get_authoring_prompt]
  kind: tool
  impl: inject_random_opener
  context_scope:
    observe:
      - get_authoring_prompt.quiz_type_used
    passthrough:
      - get_authoring_prompt.*    # Forward ALL fields from upstream
```

**UDF implementation:**
```python
import random
from agent_actions import udf_tool

OPENERS = {
    "debugging": ["During monitoring, you notice", "Your team observes"],
    "design_review": ["During a design review", "A colleague suggests"],
    "violation": ["A security review reveals", "An integration test fails because"],
}

@udf_tool()
def inject_random_opener(data: dict) -> dict:
    """Inject randomized content. Return dict (not list) when using passthrough."""
    content = data.get('content', data)

    # Get value from upstream
    quiz_type = content.get('quiz_type_used', 'general').lower()

    # Map to category
    type_to_category = {
        'consequence': 'design_review',
        'diagnosis': 'debugging',
        'violation': 'violation',
    }
    category = type_to_category.get(quiz_type, 'design_review')

    # Randomize
    opener = random.choice(OPENERS.get(category, OPENERS['design_review']))

    # Return dict with ONLY new fields (passthrough handles the rest)
    return {
        "suggested_opener": opener,
        "quiz_type": quiz_type.upper()
    }
```

**Key points:**
- With `passthrough`, return **dict** not list
- Return ONLY the new/computed fields
- Passthrough automatically merges upstream fields
- Randomization happens per-record (each gets independent value)

## Validation Aggregation Pattern

For ensemble validation with multiple voters:

```python
@udf_tool()
def aggregate_votes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Aggregate votes using majority voting."""
    content = data.get('content', data)
    votes = []

    for i in range(1, 4):
        key = f'validator_{i}'
        validator_data = content.get(key, {})
        if isinstance(validator_data, dict):
            votes.append(validator_data.get('is_valid', False))

    approve_count = sum(1 for v in votes if v)
    consensus = approve_count >= 2

    result = content.copy()
    result.update({
        'validation_status': 'PASS' if consensus else 'FAIL',
        'approve_votes': approve_count,
        'total_votes': len(votes)
    })
    return [result]
```

## Display Format Separation Pattern

Create multiple versions for different contexts:

```python
@udf_tool()
def prepare_display_versions(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create rich and plain versions of options."""
    content = data.get('content', data)
    result = content.copy()
    options = content.get('options', [])

    result['options_rich'] = options  # Original
    result['options_plain'] = [strip_formatting(opt) for opt in options]

    return [result]
```

## Version Consumption Merge Pattern

Process merged results from parallel actions:

```python
@udf_tool()
def process_merged(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    content = data.get('content', data)
    results = []

    # Data comes in nested structure after merge
    for i in range(1, 6):
        worker_key = f'process_data_{i}'
        worker_data = content.get(worker_key, {})
        if isinstance(worker_data, dict):
            results.append({
                'worker_id': i,
                'result': worker_data.get('result'),
                'score': worker_data.get('score', 0)
            })

    output = content.copy()
    output['all_results'] = results
    output['average_score'] = sum(r['score'] for r in results) / len(results) if results else 0
    return [output]
```

## Granularity Options

### Record (default) - Process one at a time
```yaml
- name: filter_questions
  kind: tool
  impl: filter_by_score
  granularity: Record
```

### File - Process all records at once
```yaml
- name: deduplicate
  kind: tool
  impl: run_dedup
  granularity: File
```

```python
@udf_tool()
def run_dedup(data: List[Dict]) -> List[Dict]:
    """File granularity receives list of all records."""
    seen = set()
    return [r for r in data if r['fact'] not in seen and not seen.add(r['fact'])]
```

## Type Mapping

| JSON | Python |
|------|--------|
| string | `str` |
| integer | `int` |
| number | `float` |
| array | `List[str]` or `List[Any]` |
| object | `dict` |
| varies | `Any` |

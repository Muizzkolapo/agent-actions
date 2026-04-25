# UDF Reference

How to write tool actions (User-Defined Functions) for agent-actions.

---

## Two types of tools

| Type | `granularity` | Called | Receives | Returns |
|------|-------------|--------|----------|---------|
| **Record** | `Record` (default) | Once per record | Observe-filtered namespaced dict | `dict` or `list[dict]` |
| **FILE** | `File` | Once with ALL records | `list[dict]` of clean business data | `list[dict]` or `FileUDFResult` |

---

## Record Mode (default)

Your tool receives observe-filtered data organized by namespace. Returns a dict with your output fields. The framework wraps it under the action namespace and carries forward all upstream namespaces.

### Basic example

```yaml
# agent_config/workflow.yml
- name: add_answer_text
  kind: tool
  impl: add_answer_text
  context_scope:
    observe:
      - write_scenario_question.*
      - validate_question_contract.*
```

```python
# tools/workflow/add_answer_text.py
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def add_answer_text(data: dict[str, Any]) -> dict:
    """Access fields by namespace — the producing action's name."""
    question = data["write_scenario_question"]["question"]
    options = data["write_scenario_question"]["options"]
    answer = data["write_scenario_question"]["answer"]

    answer_text = options[ord(answer) - ord("A")]

    return {
        "answer_text": [answer_text],
        "question": question,
        "options": options,
        "answer": [answer],
    }
```

### What the framework does

```
YOUR INPUT:                        YOUR OUTPUT:
{                                  {
  "write_scenario_question": {       "answer_text": ["..."],
    "question": "...",               "question": "...",
    "options": ["A)", "B)"],       }
  },
  "validate_question_contract": {  FRAMEWORK BUILDS:
    "pass": true,                  {
  }                                  "content": {
}                                      "source": {...},         <- upstream
                                       "write_scenario_question": {...},
                                       "add_answer_text": {     <- YOUR OUTPUT
                                         "answer_text": ["..."],
                                         "question": "...",
                                       }
                                     }
                                   }
```

### 1->N flatten

If your tool returns a list, the framework creates one record per item. Each inherits the same upstream namespaces.

```python
@udf_tool()
def flatten_questions(data: dict) -> list[dict]:
    """1 input with array -> N individual records."""
    questions = data["canonicalize_qa"]["canonical_questions"]
    return [q for q in questions if q.get("question_text")]
```

### Version merge tools

Version merge delivers double-nested data. The version namespace wraps the version's full content:

```python
@udf_tool()
def aggregate_scores(data: dict[str, Any]) -> dict:
    """Receives merged version data. Unwrap the inner namespace."""
    for i in range(1, 4):
        key = f"score_quality_{i}"
        scorer_ns = data.get(key, {})
        # Unwrap: data["score_quality_1"]["score_quality_1"]["field"]
        scorer = scorer_ns.get(key, scorer_ns) if isinstance(scorer_ns, dict) else {}
        helpfulness = scorer.get("helpfulness_score", 0)
```

### What NOT to do

```python
# BANNED -- masks missing content, hides bugs
content = data.get("content", data)

# BANNED -- flat access, fields are namespaced
question = data["question_text"]  # KeyError or wrong value

# BANNED -- framework fields, not your concern
node_id = data.get("node_id")
source_guid = data.get("source_guid")

# CORRECT -- namespaced access
question = data["flatten_canonical_questions"]["question_text"]
```

---

## FILE Mode

Your tool receives ALL records at once as clean business dicts. No framework fields (`node_id`, `source_guid`, `lineage`, `metadata`, `content` wrapper) — the framework strips those before calling you.

Each item is a `TrackedItem` (a dict subclass). You treat it as a normal dict. The framework reads hidden provenance from it when you return it.

### Imports

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult
```

### N->N passthrough (add fields)

```python
@udf_tool(granularity=Granularity.FILE)
def assign_batch_name(data: list[dict], batch_size: int = 50) -> FileUDFResult:
    return FileUDFResult(outputs=[
        {"source_index": i, "data": {**item, "batch_name": f"batch_{i // batch_size:02d}"}}
        for i, item in enumerate(data)
    ])
```

### N->M filter (dedup)

```python
@udf_tool(granularity=Granularity.FILE)
def deduplicate(data: list[dict]) -> list[dict]:
    """Filter -- returns subset of input items. TrackedItem provenance automatic."""
    seen, deduped = set(), []
    for item in data:
        key = item["question_text"]
        if key not in seen:
            seen.add(key)
            deduped.append(item)  # TrackedItem, _source_index survives
    return deduped
```

### N->M merge (combine records)

```python
@udf_tool(granularity=Granularity.FILE)
def combine_duplicates(data: list[dict]) -> FileUDFResult:
    """Merge -- creates NEW dicts, must declare provenance explicitly."""
    merged = {**data[2], **data[3], "merged_count": 2}
    return FileUDFResult(outputs=[
        {"source_index": 0, "data": data[0]},
        {"source_index": 1, "data": data[1]},
        {"source_index": [2, 3], "data": merged},  # from 2 inputs
        {"source_index": 4, "data": data[4]},
    ])
```

### 1->N expand

```python
@udf_tool(granularity=Granularity.FILE)
def split_into_clauses(data: list[dict]) -> FileUDFResult:
    """1 contract -> 3 clauses. All from same input."""
    clauses = parse_clauses(data[0]["contract_text"])
    return FileUDFResult(outputs=[
        {"source_index": 0, "data": clause}
        for clause in clauses
    ])
```

### N->1 aggregate

```python
@udf_tool(granularity=Granularity.FILE)
def aggregate_risk(data: list[dict]) -> FileUDFResult:
    """5 clause analyses -> 1 summary."""
    return FileUDFResult(outputs=[
        {"source_index": 0, "data": {
            "overall_risk": "high",
            "total_clauses": len(data),
        }},
    ])
```

---

## FILE mode return rules

| Tool pattern | Return type | User effort |
|-------------|-------------|-------------|
| Passthrough (modify in place) | `list[dict]` | None -- TrackedItem automatic |
| Filter/dedup (select subset) | `list[dict]` | None -- TrackedItem automatic |
| Enrich (add fields to items) | `list[dict]` or `FileUDFResult` | None or explicit |
| Merge (combine 2+ inputs) | `FileUDFResult` | Must declare `source_index` |
| Expand (split 1 into N) | `FileUDFResult` | Must declare `source_index` |

### `source_index` values

| Value | Meaning |
|-------|---------|
| `int` (e.g., `0`) | Output came from `input[0]` |
| `list[int]` (e.g., `[2, 3]`) | Output merged from inputs 2 and 3 |

### What FAILS

```python
# FAILS -- plain dict in list (provenance lost)
return [{"new": "dict"}, {"another": "dict"}]  # ValueError

# FAILS -- FileUDFResult output missing source_index
return FileUDFResult(outputs=[{"data": {...}}])  # ValueError

# FAILS -- FileUDFResult output missing data
return FileUDFResult(outputs=[{"source_index": 0}])  # ValueError

# FAILS -- not a list or FileUDFResult
return {"single": "dict"}  # ValueError (use Record mode instead)
```

---

## What you NEVER do

```python
# NEVER access framework fields
record.get("node_id")          # framework handles provenance
record.get("source_guid")     # framework handles identity
record["lineage"]             # framework handles lineage
record["metadata"]            # framework handles metadata

# NEVER handle content wrappers
content = data.get("content", data)  # BANNED -- framework gives you clean data

# NEVER worry about upstream namespaces
# The framework carries them forward automatically via RecordEnvelope
```

---

## Type mapping

| JSON Schema | Python |
|-------------|--------|
| `string` | `str` |
| `integer` | `int` |
| `number` | `float` |
| `boolean` | `bool` |
| `array` | `list` |
| `object` | `dict` (use TypedDict for nested objects to avoid string coercion) |

---

## CLI

```bash
agac list-udfs            # List all registered UDFs
agac validate-udfs        # Syntax check + impl resolution
```

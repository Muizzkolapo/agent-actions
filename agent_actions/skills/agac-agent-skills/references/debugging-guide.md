# Debugging Guide

Triage checklist for when things go wrong.

---

## Quick diagnostics

```bash
agac run -a workflow --fresh       # Clean run
agac render -a workflow            # See compiled YAML
```

Check `events.json` for errors. Use `record_limit: 2` to test cheaply.

---

## Triage checklist

### 1. Status tally

Check the run summary: how many OK, ERROR, SKIP?
- All SKIP → upstream failure cascading, or guard filtering everything
- First action ERROR → API key, model config, or prompt issue
- Mid-pipeline ERROR → observe resolution failure or tool bug

### 2. Guard evaluation

```
All N records filtered by guard (condition)
```

This means NO records passed the guard. Check:
- Is the condition using **namespaced** paths? `aggregate_scores.consensus_score >= 6` NOT `consensus_score >= 6`
- Are the upstream values what you expect? Query the DB.

### 3. Observe resolution errors

```
Namespace 'X' not found in record. Available: [source, A, B, C]
```

The action tried to observe from a namespace that doesn't exist. Check:
- Is the namespace name spelled correctly?
- Is it listed in `dependencies`?
- Did an upstream guard filter/skip it?

### 4. UDF data access

Fields are **namespaced**: `data["action_name"]["field"]`

```python
# WRONG -- flat access returns None or KeyError
score = data["consensus_score"]

# CORRECT -- namespaced access
score = data["aggregate_scores"]["consensus_score"]
```

For version merge tools, data is **double-nested**:
```python
# data["score_quality_1"]["score_quality_1"]["helpfulness_score"]
scorer = data.get("score_quality_1", {})
if "score_quality_1" in scorer:
    scorer = scorer["score_quality_1"]
```

### 5. Prompt template errors

```
'i' is undefined
```

Version context uses the `version` namespace: `{{ version.i }}`, `{{ version.length }}`, `{{ version.first }}`, `{{ version.last }}`. NOT bare `{{ i }}`.

### 6. Empty output

Check in order:
1. Guard filtered all records? Check condition and upstream values
2. API error? Check `events.json`
3. Schema mismatch? LLM output didn't match schema fields
4. Upstream empty? Check if the dependency action produced output

### 7. Schema drift

LLM outputs fields that don't match the schema. With `json_mode: true`, the framework validates. Check that schema field names exactly match what the prompt asks the LLM to produce.

---

## Querying the database

```python
import sqlite3, json
db = sqlite3.connect('agent_io/store/workflow.db')

# Check all actions have data
for name, count in db.execute('SELECT action_name, record_count FROM target_data ORDER BY id'):
    print(f'{name}: {count}')

# Check record structure
for name, raw in db.execute('SELECT action_name, data FROM target_data'):
    recs = json.loads(raw)
    recs = recs if isinstance(recs, list) else [recs]
    for rec in recs[:1]:
        content = rec.get('content', {})
        print(f'{name} namespaces: {list(content.keys())}')
```

---

## Full reset

```bash
rm -rf agent_io/target agent_io/.agent_status.json agent_io/source agent_io/store
mkdir -p agent_io/target
```

Both `.agent_status.json` AND the store DB must be cleared. Clearing only one causes stale state.

---

## Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `'X' is undefined` in prompt | Missing observe entry | Add `X.*` to observe |
| `namespace 'X' not found` | Upstream didn't produce namespace | Check dependencies, guard behavior |
| `Guard condition references field 'X' which does not exist` | Bare field name in guard | Use `namespace.field` format |
| All records filtered by guard | Upstream values below threshold | Check actual values in DB |
| `Environment variable 'X' not set` | Missing API key | Set in `.env` or environment |
| `Template references undefined variables: i` | Version variable without namespace | Use `{{ version.i }}` not `{{ i }}` |
| `FILE tool returned plain dict` | Tool created new dict, lost TrackedItem | Use `FileUDFResult` with `source_index` |

---

## CLI commands

```bash
agac run -a workflow                    # Run
agac run -a workflow --fresh            # Clear and re-run
agac run -a workflow --downstream       # Run from a specific action forward
agac render -a workflow                 # Compiled YAML
agac list-udfs                          # List registered tools
agac validate-udfs                      # Check tool implementations
```

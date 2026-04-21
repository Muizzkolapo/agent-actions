# Debugging Guide

Comprehensive troubleshooting for agent-actions workflows.

## Table of Contents

- [Triage Checklist](#triage-checklist)
- [Caching Behavior](#caching-behavior)
- [Validation Pipeline Overview](#validation-pipeline-overview)
- [Pre-Run Verification](#pre-run-verification)
- [Quick Diagnostics](#quick-diagnostics)
- [Common Error Messages](#common-error-messages)
- [Filtered Pipeline Debugging](#filtered-pipeline-debugging)
- [Reprompt vs Guard Decision](#reprompt-vs-guard-decision)
- [Granularity Visualization](#granularity-visualization)

## Triage Checklist

When investigating `agac run` output, follow this checklist in order. Each step catches a specific category of bug.

### 1. Tally vs Reality

Compare the tally line against what's in the storage backend. Check the workflow config for `storage_backend` type, then query accordingly:

```bash
# Check .agent_status.json for action states
cat agent_workflow/<workflow>/agent_io/.agent_status.json | python3 -m json.tool

# Check target data — look at output files per action
for dir in agent_workflow/<workflow>/agent_io/target/*/; do
  echo "=== $(basename $dir) ==="
  cat "$dir"/*.json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'  Records: {len(data)}')
if data:
    print(f'  Fields: {list(data[0].get(\"content\", data[0]).keys())[:8]}')
" 2>/dev/null || echo "  No data"
done
```

- Action marked OK with 0 records → false positive (InitialStrategy bug)
- Action missing from target but "completed" in `.agent_status.json` → stale state

### 2. Guard Evaluation

If you see unexpected skips, verify the guard condition against actual upstream data:

```bash
# Check what field values the upstream action actually produced
cat agent_workflow/<workflow>/agent_io/target/<upstream>/*.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data:
    content = r.get('content', r)
    print({k: v for k, v in content.items() if not k.startswith('_')})" 2>/dev/null
```

All comparison operators (`==`, `!=`, `>`, `>=`, `<`, `<=`) are supported. If guard results seem wrong, test the condition directly:
```python
from agent_actions.input.preprocessing.filtering.guard_filter import GuardFilter, FilterItemRequest
gf = GuardFilter()
r = gf.filter_item(FilterItemRequest(data={"field": "value"}, condition='field != "x"'))
print(r.matched)  # True — field "value" != "x"
```

### 3. First Action Failures

If the first action's API call fails (401, network error), check whether the failure was caught:
- `record_count=0` + `failed` dispositions = bug (InitialStrategy missing failure check)
- The action completes as OK, circuit breaker doesn't fire, downstream runs on empty data

### 4. CLI Status Message

"Workflow paused - batch job(s) submitted" for non-batch workflows means the CLI uses a binary check: `is_workflow_complete()` → SUCCESS, else → "batch submitted". Any failure, skip, or partial completion triggers this misleading message.

### 5. Tool UDF Data Access

If a tool action produces zero/default values:
- Fields arrive **namespaced by action name**: `content["aggregate_scores"]["consensus_score"]`
- NOT flat: `content["consensus_score"]` → returns `None`
- Check the tool code for flat `content.get("field")` patterns — these should be `content.get("action_name", {}).get("field")`

### 5a. Prompt Trace Inspection

When debugging bad LLM outputs, inspect the compiled prompt and context the LLM actually received:

```bash
# Query prompt traces from the SQLite backend
python3 -c "
import sqlite3, json
conn = sqlite3.connect('agent_workflow/<workflow>/agent_io/.agent_actions.db')
for row in conn.execute(
    'SELECT record_id, compiled_prompt, llm_context FROM prompt_trace WHERE action_name=?',
    ('<action_name>',)
).fetchmany(3):
    print(f'Record: {row[0]}')
    print(f'Prompt: {row[1][:200]}...')
    print(f'Context: {row[2][:200]}...')
    print()
"
```

Prompt traces capture the exact prompt sent to the LLM, the context data, and the response — per record, per attempt.

### 6. Schema Field Drift

If downstream actions fail with "declared fields not found":
- The LLM may produce different field names than the schema defines
- Check DB: `SELECT data FROM target_data WHERE action_name='<action>';`
- Compare actual keys against schema `id:` values

---

## Validation Pipeline Overview

LLM outputs pass through three validation layers:

```mermaid
flowchart TD
    A[LLM Response] --> B{Layer 1: JSON Valid?}
    B -->|No| C[JSON Repair]
    C --> D{Repaired?}
    D -->|No| E[Reprompt]
    D -->|Yes| F
    B -->|Yes| F{Layer 2: Schema Valid?}
    F -->|No| G{Reprompt Enabled?}
    G -->|Yes| E
    G -->|No| H[Action Fails]
    E --> A
    F -->|Yes| I{Layer 3: Guard Passes?}
    I -->|No - filter| J[Record Removed]
    I -->|No - skip| K[Action Skipped]
    I -->|Yes| L[Output Accepted]

    style L fill:#90EE90
    style J fill:#ffcccc
```

| Layer | Purpose | Mechanism |
|-------|---------|-----------|
| **1. JSON** | Structural integrity | JSON repair + reprompt |
| **2. Schema** | Type/field validation | Schema constraints + reprompt |
| **3. Guard** | Semantic validation | Condition expressions |

## Pre-Run Verification

Before running a workflow, check these common blockers:

```bash
# 1. API keys exist for all vendors used
env | grep -E "OPENAI_API_KEY|ANTHROPIC_API_KEY|GROQ_API_KEY" | cut -d= -f1

# 2. Seed files referenced in config actually exist
ls agent_workflow/<workflow>/seed_data/

# 3. Clear stale cache from failed prior runs
rm -rf agent_workflow/<workflow>/agent_io/target/*
rm -rf agent_workflow/<workflow>/agent_io/source/
```

## Caching Behavior

Actions cache their results in `.agent_status.json` (stored at `agent_workflow/<workflow>/agent_io/.agent_status.json`). Understanding caching prevents both stale data bugs and unnecessary re-runs.

### How skip-vs-rerun decisions work

When you run `agac run`, the framework checks each action:

1. Is the action's status `completed` in `.agent_status.json`?
2. Does the action have actual output files in the storage backend?
3. Does the action have a `FAILED` or `SKIPPED` disposition flag?

Only if (1) is yes AND (2) is yes AND (3) is no does the framework skip re-execution.

### What invalidates the cache

| Change | Cache invalidated? |
|--------|-------------------|
| Modify `record_limit` or `file_limit` | Yes — automatically detected |
| Change prompt text | No — must clear manually |
| Change schema | No — must clear manually |
| Change model/vendor | No — must clear manually |
| Upstream action re-runs | No — must clear manually |

The framework stores `record_limit` and `file_limit` values as metadata when an action completes. If these values differ on the next run, the action resets to PENDING automatically.

For all other config changes, clear the cache manually. **CRITICAL: You must clear ALL THREE stores** — missing any one causes silent failures:

```python
# Full reset script — use this pattern every time
import sqlite3, json, shutil, os

db_path = 'agent_workflow/<workflow>/agent_io/target/<workflow>.db'
conn = sqlite3.connect(db_path)
actions = ['action_1', 'action_2']  # actions to reset
for a in actions:
    conn.execute('DELETE FROM target_data WHERE action_name=?', (a,))
    conn.execute('DELETE FROM record_disposition WHERE action_name=?', (a,))  # CRITICAL — forgetting this causes "All records guard-skipped"
conn.commit(); conn.close()

# Remove target folders (stale batch files override YAML config)
base = 'agent_workflow/<workflow>/agent_io/target'
for a in actions:
    p = os.path.join(base, a)
    if os.path.isdir(p): shutil.rmtree(p)

# Reset status
path = 'agent_workflow/<workflow>/agent_io/.agent_status.json'
with open(path) as f: data = json.load(f)
for a in actions:
    if a in data:
        data[a]['status'] = 'pending'
        data[a].pop('skip_reason', None)
        data[a].pop('error_message', None)
with open(path, 'w') as f: json.dump(data, f, indent=4)
```

**Why all three?**
- Missing `target_data` clear → old data used instead of fresh run
- Missing `record_disposition` clear → "All records guard-skipped" (stale entries block processing)
- Missing status reset → action skipped as "completed"
- Missing target folder removal → stale batch files override `run_mode` config

### enable_caching flag

`enable_caching: true` is the default. Setting `enable_caching: false` on an action disables result caching — the action re-runs every time.

```yaml
- name: volatile_action
  enable_caching: false                # Always re-run
```

### Stale Cache Diagnosis

**Symptom:** Re-running after a failure completes in 0.03s. Actions show "completed" with empty output.

**Cause:** Failed runs cache empty results. The framework sees "completed" status and skips re-execution, serving cached empties.

**Diagnosis:**
```bash
# Check for suspiciously fast completions and empty outputs
for dir in agent_workflow/<workflow>/agent_io/target/*/; do
  size=$(wc -c < "$dir/sample.json" 2>/dev/null || echo "0")
  if [ "$size" -le 2 ]; then
    echo "EMPTY: $dir"
  fi
done
```

**Fix:** Clear target and source directories, then re-run:
```bash
rm -rf agent_workflow/<workflow>/agent_io/target/*
rm -rf agent_workflow/<workflow>/agent_io/source/
agac run -a <workflow>
```

## Quick Diagnostics

### Check Record Counts Per Stage

```bash
cd agent_workflow/my_workflow/agent_io/target
for dir in */; do
  count=$(cat "$dir/sample.json" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  echo "$count records - $dir"
done
```

### Check File Sizes for Empty Outputs

```bash
# 2 bytes = empty array []
ls -lh */sample.json | awk '{print $5 " - " $9}'
```

### Analyze Validation Results

```bash
cat validate_code_quality/sample.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Total: {len(data)} records')
for i, record in enumerate(data, 1):
    content = record.get('content', {})
    status = content.get('validation_status', 'unknown')
    print(f'  Record {i}: {status}')
    if status != 'PASS':
        reasoning = content.get('validation_reasoning', '')[:150]
        print(f'    Reason: {reasoning}...')
"
```

## Common Error Messages

| Error | Cause | Fix |
|-------|-------|-----|
| "X was unexpected" | Field in data not in TypedDict | Add field to TypedDict |
| "X is not of type Y" | Type mismatch | Use correct type or `Any` |
| "Duplicate UDF function name" | Same name in multiple dirs | Remove duplicate or rename |
| "Dependency not in context_scope" | Missing reference | Add `action.*` to observe |
| "declared fields not found" | Schema field name doesn't match LLM output | Rename schema `id:` to match actual output |
| "None is not of type 'object'" | Guard-filtered upstream, schema expects non-null | Remove from schema or handle None in tool |
| "Additional properties are not allowed" | Tool returns fields not in schema | Add fields to schema (outside `required`) |
| "batch job(s) submitted" (no batch) | CLI catch-all for non-complete state | Check actual errors in tally/DB |
| "Drop directive matched zero fields" | Drop targets unreachable namespace | Remove the drop or ignore the warning |

## Filtered Pipeline Debugging

When guards filter records and downstream actions have 0 output:

### Symptom
```
validate_code_quality: 5 records
generate_explanation:  0 records  ← All filtered!
```

### Debugging Steps

1. Check upstream output for field values
2. Verify guard condition matches data exactly (case-sensitive)
3. Temporarily disable guard to test flow

### Fix Options

- Fix upstream prompts to produce passing values
- Lower threshold: `>= 7` instead of `>= 8`
- Allow multiple statuses: `'status == "PASS" or status == "NEEDS_REVIEW"'`

## Known Tool Limitations

| Issue | Workaround |
|-------|------------|
| Manifest shows "pending" after completion | Count records from sample.json |
| run_results.json empty | Check individual action outputs |
| Validation at runtime only | Check events.json on "success" |

## Debug Commands

```bash
# See compiled workflow (schemas inlined, versions expanded)
agac render -a my_workflow

# Run with debug output
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow

# Execute workflow
agac run -a my_workflow
```

### Debugging Schema Issues

Use `agac render` to verify schemas are compiled correctly:

```bash
agac render -a my_workflow | grep -A 10 "schema:"
```

This shows inlined schemas - if you see `schema_name:` still present, the schema file may be missing.

## Granularity Visualization

### Record Granularity (default)
Each record processed independently:

```mermaid
flowchart LR
    subgraph input["Input (3 records)"]
        I1[Record 1]
        I2[Record 2]
        I3[Record 3]
    end
    subgraph action["Record Granularity Action"]
        A1[Process 1]
        A2[Process 2]
        A3[Process 3]
    end
    subgraph output["Output (3 results)"]
        O1[Result 1]
        O2[Result 2]
        O3[Result 3]
    end
    I1 --> A1 --> O1
    I2 --> A2 --> O2
    I3 --> A3 --> O3
```

### File Granularity
All records processed at once (for aggregation/dedup):

```mermaid
flowchart LR
    subgraph input["Input (3 records)"]
        I1[Record 1]
        I2[Record 2]
        I3[Record 3]
    end
    subgraph action["File Granularity Action"]
        A["Process ALL"]
    end
    subgraph output["Output (variable)"]
        O1[Result 1]
        O2[Result 2]
    end
    I1 --> A
    I2 --> A
    I3 --> A
    A --> O1
    A --> O2

    style A fill:#87CEEB
```

**Note:** Guards are NOT supported with File granularity - implement filtering in your UDF.

## Reprompt vs Guard Decision

```mermaid
flowchart TD
    Q["Validation Failed"] --> A{Can LLM fix it?}
    A -->|Yes - structural issue| B["Use Reprompt"]
    A -->|No - semantic choice| C["Use Guard"]

    B --> D["Costs more tokens<br/>Retries LLM call"]
    C --> E["Free<br/>Filters record"]

    style B fill:#FFE4B5
    style C fill:#90EE90
```

| Use Reprompt | Use Guard |
|--------------|-----------|
| Malformed JSON | Valid but unwanted value |
| Schema violation | Score below threshold |
| Missing required field | Wrong category |
| LLM can learn from error | Business logic decision |

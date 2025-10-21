# Guard vs WHERE Clause - What's the Difference?

**Quick Answer**: No, they're **different features** with **different purposes** and **different timing** in the workflow.

---

## TL;DR Summary

| Feature | Purpose | When It Runs | Scope | Behavior Options |
|---------|---------|--------------|-------|------------------|
| **WHERE clause** | Pre-filter input data **before** sending to LLM | Before batch submission | Item-level or dataset-level | `skip` or `filter` |
| **guard** | Validate LLM output **after** generation | After LLM returns result | Action-level only | `skip` or `filter` |

---

## Visual Comparison

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        WORKFLOW DATA FLOW                                │
└─────────────────────────────────────────────────────────────────────────┘

Input Data (100 items)
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ WHERE CLAUSE (Pre-filter)                           │  ← RUNS FIRST
│ Condition: item.status == "active"                  │
│ on_false: "skip" or "filter"                        │
├─────────────────────────────────────────────────────┤
│ Result: 80 items pass (20 skipped/filtered)         │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
                80 items sent to LLM
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│ LLM PROCESSING (Batch)                              │
│ - OpenAI/Anthropic/Ollama/Gemini                    │
│ - Generates output for each item                    │
├─────────────────────────────────────────────────────┤
│ Result: 80 outputs generated                        │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
                80 LLM outputs
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│ GUARD (Post-validation)                             │  ← RUNS LAST
│ Condition: candidate_facts_list != []               │
│ on_false: "skip" or "filter"                        │
├─────────────────────────────────────────────────────┤
│ Result: 75 items pass (5 have empty facts lists)    │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
                75 items to next agent
                (or final output)
```

---

## WHERE Clause (Pre-Filter)

### Purpose
Filter **input data** before sending to the LLM to avoid wasting API calls on items you don't want to process.

### Configuration
```yaml
agents:
  fact_extractor:
    where_clause:
      clause: "status == 'active' AND priority > 5"  # SQL-like condition
      scope: "item"  # Or "dataset"
      behavior: "skip"  # Or "filter"
```

### When It Runs
**BEFORE** the batch is submitted to the LLM provider.

```
Input data → WHERE clause → Filtered data → LLM
```

### Scope Options

#### `scope: "item"` (Default)
Evaluates condition for **each item individually**.

```yaml
where_clause:
  clause: "status == 'active'"
  scope: "item"
  behavior: "skip"
```

**Example:**
```
Input: [
  {"id": 1, "status": "active"},   ✅ Passes
  {"id": 2, "status": "inactive"}, ❌ Skipped
  {"id": 3, "status": "active"}    ✅ Passes
]

Result: Only items 1 and 3 are sent to LLM
```

#### `scope: "dataset"`
Evaluates condition on the **entire dataset**.

```yaml
where_clause:
  clause: "len(data) > 10"
  scope: "dataset"
  behavior: "filter"
```

**Example:**
```
If dataset has < 10 items → entire batch is filtered/skipped
If dataset has ≥ 10 items → entire batch proceeds
```

### Behavior Options

#### `behavior: "skip"`
Items that don't match are **passed through** with metadata indicating they were skipped.

```json
{
  "target_id": "2",
  "content": {"original": "data"},
  "metadata": {
    "skipped_by_where_clause": true,
    "agent_type": "passthrough",
    "reason": "where_clause_not_matched"
  }
}
```

**Use when:** You want to preserve the record in the workflow (e.g., for lineage tracking).

#### `behavior: "filter"`
Items that don't match are **completely removed** from the workflow.

**Use when:** You don't need these records at all.

### Code Location
- Parser: `agent_actions/core/parser/where_parser.py`
- Evaluation: `batch_service.py` lines 362-370

---

## Guard (Post-Validation)

### Purpose
Validate **LLM output** after generation to ensure quality, handle empty results, or enforce business rules.

### Configuration
```yaml
agents:
  fact_extractor:
    output_field: "candidate_facts_list"
    guard:
      condition: 'candidate_facts_list != []'  # Can be SQL-like or UDF
      on_false: "filter"  # Or "skip"
```

### When It Runs
**AFTER** the LLM generates output, during the action processing phase.

```
LLM → Output → Guard → Valid outputs → Next agent
```

### Scope
**Action-level only** - evaluates the generated output for each item.

### Condition Types

#### SQL-like Expression
```yaml
guard:
  condition: 'candidate_facts_list != []'
  on_false: "filter"
```

Evaluates Python expressions against the LLM output.

#### UDF (User-Defined Function)
```yaml
guard:
  condition: 'udf:validators.check_quality'
  on_false: "skip"
```

Calls a custom Python function:

```python
# validators.py
def check_quality(data):
    """Return True if data meets quality standards."""
    if not data.get('candidate_facts_list'):
        return False
    if len(data['candidate_facts_list']) < 3:
        return False
    return True
```

### Behavior Options

#### `on_false: "skip"`
Failed items are **passed through** with metadata.

```json
{
  "target_id": "5",
  "content": {"candidate_facts_list": []},
  "metadata": {
    "skipped_by_guard": true,
    "reason": "guard_condition_failed"
  }
}
```

#### `on_false: "filter"`
Failed items are **removed** from the workflow.

### Code Location
- Config: `agent_actions/core/utils/consolidated_guard.py`
- Evaluation: Action processing in workflow engine

---

## Key Differences

### 1. Timing

**WHERE clause:**
```
┌─────┐   WHERE   ┌─────┐   LLM   ┌────────┐
│Data │ ────────→ │ 80  │ ──────→ │80 calls│
│ 100 │           │items│         │ $$$    │
└─────┘           └─────┘         └────────┘
```

**Guard:**
```
┌─────┐   LLM     ┌────────┐  Guard  ┌─────┐
│Data │ ────────→ │100 calls│ ──────→ │ 75  │
│ 100 │           │  $$$$$  │         │items│
└─────┘           └─────────┘         └─────┘
```

**Cost Implication:**
- WHERE clause: **Saves money** (fewer LLM calls)
- Guard: **Costs money** (validates after LLM call)

### 2. What They Evaluate

**WHERE clause:**
- Evaluates **input data** (what you send to LLM)
- Access to: original item fields, metadata, context

```yaml
where_clause:
  clause: "priority > 5 AND status == 'active'"  # Input fields
```

**Guard:**
- Evaluates **output data** (what LLM returns)
- Access to: LLM-generated fields, output_field

```yaml
guard:
  condition: "candidate_facts_list != []"  # Output field
```

### 3. Use Cases

#### WHERE Clause Use Cases

**✅ Use WHERE clause to:**
- Skip items already processed: `processed == false`
- Filter by priority: `priority >= 3`
- Filter by date range: `created_at > '2024-01-01'`
- Skip test data: `is_test == false`
- Dataset size checks: `len(data) > 100` (scope: dataset)

**Example:**
```yaml
# Don't process items that were already reviewed
where_clause:
  clause: "reviewed == false"
  scope: "item"
  behavior: "filter"
```

**Benefit:** Saves API costs by not sending unnecessary items to LLM.

#### Guard Use Cases

**✅ Use guard to:**
- Reject empty outputs: `result != ""`
- Enforce minimum quality: `confidence > 0.8`
- Validate structure: `len(facts) >= 3`
- Business rule validation: `udf:validators.meets_sla`
- Skip low-quality generations for retry

**Example:**
```yaml
# Only accept facts if we extracted at least 3
guard:
  condition: 'len(candidate_facts_list) >= 3'
  on_false: "skip"  # Pass through for manual review
```

**Benefit:** Ensures quality control on LLM outputs before proceeding.

---

## Common Patterns

### Pattern 1: Cost Optimization (WHERE clause)

```yaml
agents:
  summarizer:
    where_clause:
      # Don't summarize short texts (waste of API call)
      clause: "len(text) > 500"
      scope: "item"
      behavior: "filter"
```

**Why:** Avoids paying for LLM calls on data that doesn't need processing.

### Pattern 2: Quality Control (Guard)

```yaml
agents:
  fact_extractor:
    output_field: "facts"
    guard:
      # Only accept if we found facts
      condition: 'facts != []'
      on_false: "skip"  # Pass through for human review
```

**Why:** Ensures LLM actually extracted meaningful information.

### Pattern 3: Combined (Both!)

```yaml
agents:
  analyzer:
    # Pre-filter: Only analyze high-priority items
    where_clause:
      clause: "priority >= 3"
      scope: "item"
      behavior: "filter"

    # Post-validate: Ensure analysis has minimum quality
    output_field: "analysis"
    guard:
      condition: 'udf:validators.analysis_quality'
      on_false: "skip"
```

**Why:**
1. WHERE clause reduces API costs (only process priority items)
2. Guard ensures quality (only accept good analyses)

---

## Configuration Examples

### Example 1: WHERE Clause Only

```yaml
workflow_id: active_users_only
agents:
  user_analyzer:
    model_vendor: openai
    model_name: gpt-4o-mini

    # Only process active users with recent activity
    where_clause:
      clause: "status == 'active' AND last_login > '2024-01-01'"
      scope: "item"
      behavior: "filter"  # Remove inactive users entirely
```

**Result:** Inactive users never sent to LLM (saves money).

### Example 2: Guard Only

```yaml
workflow_id: fact_extraction
agents:
  fact_extractor:
    model_vendor: anthropic
    model_name: claude-3-5-sonnet-20241022
    output_field: "facts"

    # Validate LLM output quality
    guard:
      condition: 'len(facts) >= 2 AND all(len(f) > 10 for f in facts)'
      on_false: "skip"  # Pass through for manual review
```

**Result:** Items with low-quality facts are flagged but preserved.

### Example 3: Both (Recommended for Production)

```yaml
workflow_id: smart_processing
agents:
  processor:
    model_vendor: gemini
    model_name: gemini-1.5-flash
    output_field: "processed_data"

    # Step 1: Pre-filter (save money)
    where_clause:
      clause: "needs_processing == true AND priority > 2"
      scope: "item"
      behavior: "filter"

    # Step 2: Post-validate (ensure quality)
    guard:
      condition: 'udf:validators.quality_check'
      on_false: "skip"
```

**Result:**
1. Only necessary items sent to LLM ✅
2. Only quality outputs proceed to next agent ✅

---

## Decision Tree: Which One to Use?

```
Do you want to filter BEFORE sending to LLM?
├─ Yes → Use WHERE clause
│         ├─ Want to preserve records? → behavior: "skip"
│         └─ Want to remove records? → behavior: "filter"
│
└─ No → Do you want to validate AFTER LLM generates output?
          ├─ Yes → Use guard
          │         ├─ Want to preserve records? → on_false: "skip"
          │         └─ Want to remove records? → on_false: "filter"
          │
          └─ No → Use neither (process all items)

Want both cost optimization AND quality control?
└─ Use WHERE clause + guard together! 🎯
```

---

## Summary Table

| Aspect | WHERE Clause | Guard |
|--------|-------------|-------|
| **Runs** | Before LLM | After LLM |
| **Evaluates** | Input data | Output data |
| **Purpose** | Filter what to process | Validate what was generated |
| **Cost Impact** | Saves money (fewer calls) | Costs money (validates after call) |
| **Scope** | Item or dataset | Action only |
| **Syntax** | SQL-like | SQL-like or UDF |
| **on_false** | `skip` or `filter` | `skip` or `filter` |
| **Use for** | Priority filtering, status checks | Quality validation, empty result handling |

---

## Answer to Your Question

```yaml
guard:
  condition: 'candidate_facts_list != []'
  on_false: "filter"
```

This is a **guard** (post-validation), not a WHERE clause!

**What it does:**
- Runs **AFTER** the LLM generates `candidate_facts_list`
- Checks if the list is not empty
- If empty → item is **filtered out** (removed from workflow)

**Equivalent WHERE clause would be:**
```yaml
where_clause:
  clause: "candidate_facts_list != []"  # Check INPUT field
  scope: "item"
  behavior: "filter"
```

But this checks the **input data** before LLM, not the **output**.

**Key difference:**
- Guard: "Did the LLM generate good facts?" (after)
- WHERE: "Does this input item have facts already?" (before)

Most likely you want the **guard** (validate LLM output)!

---

## Best Practices

### ✅ DO:
- Use WHERE clause to reduce API costs
- Use guard to ensure output quality
- Use both together for production workflows
- Use `skip` when you need audit trail
- Use `filter` when you don't need those records

### ❌ DON'T:
- Use guard for input validation (use WHERE clause)
- Use WHERE clause for output validation (use guard)
- Skip both if you need all items processed
- Confuse the two (they run at different times!)

---

## Code References

### WHERE Clause
- **Parser**: `agent_actions/core/parser/where_parser.py`
- **Evaluation**: `batch_service.py:362-370`
- **Test**: `tests/tasks/test_batch_service_integration.py:140`

### Guard
- **Config**: `agent_actions/core/utils/consolidated_guard.py:16`
- **Types**: `GuardBehavior.SKIP` or `GuardBehavior.FILTER`
- **Test**: `tests/core/utils/test_consolidated_guard.py:65`

---

**Final Answer**: No, they're completely different features!
- WHERE clause = pre-filter (before LLM) 💰
- Guard = post-validation (after LLM) ✅

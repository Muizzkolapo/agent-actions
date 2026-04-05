---
name: agent-actions-workflow
description: Build and debug agent-actions agentic workflows. Use when creating workflows, writing UDFs, configuring guards, setting up parallel/versioned actions, or debugging filtered pipelines with empty outputs. CRITICAL - Before creating or modifying ANY action, ALWAYS read the workflow first, understand the action anatomy, check parent outputs, and verify child inputs. Never make changes without understanding the full context. ALWAYS ask clarifying questions about goals, inputs, outputs, and edge cases before writing any code.
---

# Agent Actions Workflow Builder

Build production-ready agent-actions workflows with YAML configs, UDF tools, and proper context scoping.

## Pre-Flight Checklist

**BEFORE creating or modifying ANY action:**

1. **Read the workflow YAML** -- understand the full pipeline and all action names.
2. **Check parent outputs** -- query the DB or read `agent_io/target/<parent>/sample.json` to see actual field names and values.
3. **Check child inputs** -- what does each downstream action `observe`? Will your output satisfy it?
4. **Check guards** -- does the condition field actually exist in the upstream output? Are the values what you expect?
5. **Check schema field names** -- do they match what the LLM prompt asks for and what downstream actions reference?
6. **Ask clarifying questions** -- do not assume goals, thresholds, model choices, or edge-case behavior.

---

## Triage Run Output

When the user shares `agac run` output, follow this checklist systematically.

### 1. Tally vs Reality

Compare the tally line (e.g. `5 OK | 2 SKIP | 1 ERROR`) against what actually happened:

- Count actions in the YAML. Does `OK + SKIP + ERROR` equal the total?
- Check the storage backend (target data + dispositions):
  ```sql
  SELECT action_name, record_count FROM target_data;
  SELECT * FROM record_disposition;
  ```
- Any action marked OK with `record_count = 0` or all dispositions `failed`/`unprocessed` is a **false positive**.
- Any action missing from `target_data` but marked `"completed"` in `.agent_status.json` is suspicious.

### 2. Guard / Filter Evaluation

If any action has a `guard:` with `condition:`, verify the guard is evaluating correctly:

- Check the **actual field values** in the upstream action's `target_data`.
- **Known parser bug:** The `WhereClauseParser` silently maps `!=`, `>` to `==` because `_map_operator_name` defaults to `ComparisonOperator.EQ`. If you see unexpected guard skips, test the condition directly:
  ```python
  from agent_actions.input.preprocessing.filtering.guard_filter import GuardFilter, FilterItemRequest
  gf = GuardFilter()
  r = gf.filter_item(FilterItemRequest(data={"field": "value"}, condition='field != "x"'))
  print(r.matched)
  ```

### 3. First Action Failure

If the **first action** fails (e.g. invalid API key), check whether it was actually caught:

- **Known bug:** `InitialStrategy` (in `initial_pipeline.py`) is missing the failure detection check that `StandardStrategy` has. All records can fail and the action still completes as OK with `record_count = 0`.
- Look for `record_count = 0` in `target_data` combined with `failed` dispositions in `record_disposition`.

### 4. CLI Status Message

If the final message says "batch job(s) submitted" but the workflow has no batch actions (`run_mode: online`):

- **Known bug:** `cli/run.py` uses a binary check -- `is_workflow_complete()` returns SUCCESS, anything else triggers the "batch job(s) submitted" message. Any failure, skip, or incomplete state produces this misleading output.

### 5. Guard-Skipped Actions in Tally

If actions that did no real work (all records guard-skipped) show as OK:

- **Known bug:** Per-record guard skips produce tombstone output (`record_count > 0`), so the action "completes" successfully. The tally counts it as OK even though no LLM call was made.
- Check `record_disposition` for `unprocessed | guard_skip` or `unprocessed | upstream_unprocessed`.

### 6. Circuit Breaker

If a failed action's downstream dependents still ran:

- Verify the failed action has status `"failed"` in `.agent_status.json` (not `"completed"`).
- If the action completed despite all records failing (see points 2 and 3), the circuit breaker could not fire.

### 7. Event Log

Read `events.json` for the run's `invocation_id`:
- `"Guard: condition not matched"` when records should have passed
- `"Non-retriable error"` followed by action completing as OK
- `"Processing failed for source_guid"` without a corresponding action failure

### Investigation Flow

```
1. Read the workflow YAML config
2. Check the storage backend for target data and dispositions
3. Read .agent_status.json
4. Check events.json
5. Cross-reference findings against the checklist above
```

---

## Quick Reference

```bash
agac run -a my_workflow              # Run workflow
agac run -a my_workflow --upstream   # With upstream deps
agac render -a my_workflow           # See compiled YAML (schemas inlined, versions expanded)
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow  # Debug output
```

## Project Structure

```
project/
 agent_actions.yml                  # Project configuration
 agent_workflow/
   my_workflow/                     # Directory name must match workflow name!
     agent_config/
       my_workflow.yml              # YAML filename must match workflow name!
     agent_io/
       staging/                     # Input data
       source/                      # Auto-generated with metadata
       target/                      # Output per action + storage backend + events.json
     seed_data/                     # Reference data (optional)
 prompt_store/                      # Prompt templates
 schema/                            # Output schemas (root only!)
 tools/
   my_workflow/                     # UDFs organized by workflow
```

**Naming rule:** Directory name = YAML filename = `name:` field in YAML. Use underscores, not hyphens.

## Core Concepts

### Dependencies vs Context Scope

- **`dependencies`** -- controls WHEN an action runs (execution order).
- **`context_scope`** -- controls WHAT data an action accesses (via lineage).

```yaml
- name: generate_answer
  dependencies: [validate_data]           # Run AFTER validate_data
  context_scope:
    observe:
      - validate_data.*                   # Access validate_data output
      - source.page_content               # Access original source via lineage
```

### Action Types

**LLM Action:**
```yaml
- name: generate_explanation
  dependencies: [previous_action]
  model_vendor: openai
  model_name: gpt-4o-mini
  schema: { explanation: string }
  prompt: $workflow.Prompt_Name
  context_scope:
    observe:
      - previous_action.*
```

**Tool Action (UDF):**
```yaml
- name: process_data
  dependencies: [previous_action]
  kind: tool
  impl: function_name                     # Must match @udf_tool function
  granularity: Record                     # Record (default) | File (rare)
  context_scope:
    observe:
      - previous_action.*
```

### Guards (Conditional Filtering)

```yaml
guard:
  condition: 'validation_status == "PASS" and score >= 8'
  on_false: "filter"    # filter | skip
```

Guards check **INPUT** (the upstream action's output). Place the guard on the **consuming** action:

```yaml
- name: validate_data        # Produces validation_status -- no guard here

- name: use_validated
  dependencies: [validate_data]
  guard:
    condition: 'validation_status == "PASS"'   # Checks validate_data OUTPUT
```

### Versioned Parallel Actions

```yaml
- name: generate_alternatives
  versions:
    param: alt_num
    range: [1, 2, 3]
    mode: parallel
  schema:
    alternative_${alt_num}: string

- name: merge_alternatives
  dependencies: [generate_alternatives]
  version_consumption:
    source: generate_alternatives
    pattern: merge
  context_scope:
    observe:
      - generate_alternatives.*           # Wildcard captures ALL versions
```

**Available version variables:** `{{ i }}` (current value), `{{ idx }}` (zero-based), `{{ version.length }}`, `{{ version.first }}`, `{{ version.last }}`. These work in both inline prompts and prompt store references.

### Cross-Workflow Dependencies

```yaml
dependencies:
  - workflow: upstream_workflow
    action: final_action                  # Use ACTION name, not impl name!
context_scope:
  observe:
    - final_action.*
```

---

## UDF Essential Pattern

### Data Access -- CRITICAL

**Tool UDFs receive upstream fields FLAT in `content`, NOT namespaced.**

```python
# CORRECT -- fields are flat in content
score = content.get("consensus_score", 0)

# WRONG -- always returns the default, the namespace does not exist in content
score = content.get("aggregate_scores", {}).get("consensus_score", 0)
```

This is the single most common UDF bug. The framework flattens all observed fields into `content` before calling your function. There are no nested action namespaces inside `content`.

### Template

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def my_function(data: dict[str, Any]) -> list[dict[str, Any]]:
    # STEP 1: Handle content wrapper (safety net -- usually already unwrapped)
    content = data.get('content', data)

    # STEP 2: Forward fields + add computed
    result = content.copy()
    result['computed_field'] = some_calculation(content)

    # STEP 3: Return as LIST (REQUIRED)
    return [result]
```

When using `passthrough` in the YAML config, return a **dict** (not list) with only the new/changed fields.

---

## Retry & Reprompt

### Retry (Transient Errors)

Handles transient failures: HTTP 429 (rate limit), timeouts, 502/503 errors. The framework retries the entire API call.

```yaml
defaults:
  retry:
    max_attempts: 2          # 1 original + 1 retry
    on_exhausted: return_last  # return_last | raise
```

### Reprompt (Bad LLM Output)

Handles cases where the LLM returned a response but the output is bad: null fields, wrong types, schema violations. The framework re-sends the prompt with error feedback.

```yaml
defaults:
  reprompt:
    max_attempts: 4
    on_exhausted: return_last  # return_last | raise
```

### Custom Reprompt Validation

For business-logic validation (not just schema), write a validation UDF and reference it:

```yaml
- name: extract_details
  reprompt:
    max_attempts: 3
    validation: check_required_fields
    on_exhausted: return_last
```

**Generic validation UDF** (place in `tools/shared/reprompt_validations.py`):

```python
from agent_actions import udf_tool

@udf_tool()
def check_required_fields(data: dict) -> dict:
    """Validate LLM output has non-empty required fields."""
    content = data.get("content", data)
    errors = []

    for field in ["title", "description", "category"]:
        val = content.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"'{field}' is missing or empty")

    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "errors": []}
```

---

## Multi-Vendor Model Selection

Use `defaults` to set the baseline vendor, then override per-action for cost optimization.

```yaml
defaults:
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: $OPENAI_API_KEY

actions:
  - name: classify_input          # Easy task -- cheap model
    model_vendor: groq
    model_name: llama-3.1-70b-versatile
    api_key: $GROQ_API_KEY
    schema: { category: string }

  - name: generate_analysis       # Hard task -- strong model
    model_vendor: anthropic
    model_name: claude-sonnet-4-20250514
    api_key: $ANTHROPIC_API_KEY
    schema: { analysis: string, reasoning: string }
```

**Rules of thumb:**
- Extraction, classification, formatting --> cheaper models (Groq, Ollama, Gemini Flash)
- Reasoning, synthesis, creative writing --> stronger models (OpenAI GPT-4o, Anthropic Claude)
- Each per-action override needs its own `api_key:` field

---

## Configuration Hierarchy

```
agent_actions.yml (Project) --> workflow.yml defaults --> action-level fields
```

Higher specificity wins. Action-level fields override defaults, which override project config.

## Prompt Templates

Define in `prompt_store/workflow_name.md`:

```markdown
{prompt Extract_Facts}
Extract from: {{ source.page_content }}
Previous result: {{ previous_action.field }}
{end_prompt}
```

Reference: `prompt: $workflow_name.Extract_Facts`

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Guard on wrong action | Place on NEXT action (guard checks INPUT) |
| UDF forgot content wrapper | Always: `content = data.get('content', data)` |
| UDF returns dict instead of list | Must return `[result]` (unless using passthrough) |
| UDF accesses namespaced fields in content | Fields are FLAT: `content.get("field")`, not `content.get("action", {}).get("field")` |
| Dependency not in context_scope | Add `action.*` to observe |
| Cross-workflow uses impl name | Use action name, not impl |
| Schema in subdirectory | Must be in root `schema/` |
| Missing passthrough | Add `passthrough: [upstream.*]` to forward fields |
| Using `loop:` / `loop_consumption:` | Use `versions:` / `version_consumption:` |
| Schema without `name` field | Add `name:`, `description:`, `fields:` structure |
| `seed_data.` in observe/prompts | Config key is `seed_data:`, reference prefix is `seed.` |
| Schema with folder prefix | Use `schema: name` not `schema: workflow_name/name` |
| Referencing non-existent fields | Check actual output: `cat agent_io/target/<action>/sample.json` |
| Wrong namespace after passthrough | Fields become `current_action.field`, not `original_action.field` |
| `!=` or `>` in guard condition | **Known parser bug:** these silently evaluate as `==`. Test guards manually. |
| First action fails silently | **Known bug:** `InitialStrategy` marks action OK even when all records fail. Check `record_count` and dispositions. |
| Guard-skipped action counted as OK | **Known bug:** tombstone output means tally sees success. Check `record_disposition` for `guard_skip`. |
| CLI says "batch job(s) submitted" | **Known bug:** any non-success state triggers this message, even for online-mode workflows. |
| Drop directive on unreachable namespace | Harmless runtime warning -- safe to ignore. |

## Detailed Reference Files

- **[Action Anatomy](references/action-anatomy.md)** - Action structure, components, and data flow
- **[Workflow Patterns](references/workflow-patterns.md)** - Diamond, ensemble, conditional merge patterns
- **[UDF Patterns](references/udf-patterns.md)** - Field forwarding, validation aggregation, version consumption
- **[UDF Decorator](references/udf-decorator.md)** - @udf_tool() API, granularity options, input/output contracts
- **[Context Scope Guide](references/context-scope-guide.md)** - observe, drop, passthrough, seed_path directives
- **[Dynamic Content Injection](references/dynamic-content-injection.md)** - Randomized prompts, computed values, tool action injection
- **[Data Flow Patterns](references/data-flow-patterns.md)** - Directory structure, metadata fields, content wrapper format
- **[Prompt Patterns](references/prompt-patterns.md)** - Prompt store syntax, Jinja2 templates, field references
- **[YAML Schema](references/yaml-schema.md)** - Complete YAML configuration reference
- **[CLI Reference](references/cli-reference.md)** - agac commands, flags, and usage
- **[Debugging Guide](references/debugging-guide.md)** - Error messages, filtered pipeline debugging, known limitations
- **[Common Pitfalls](references/common-pitfalls.md)** - Detailed explanations and fixes for frequent mistakes

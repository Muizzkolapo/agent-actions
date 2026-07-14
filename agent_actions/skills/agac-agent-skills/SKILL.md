---
name: agac-agent-skills
description: Build, run, inspect, and debug agent-actions workflows. Triggers on workflow YAML, UDFs, observe/passthrough/drop, guards, versions, schemas, seed data, prompts, HITL, running or resetting a pipeline, or debugging empty/filtered output.
---

# Agent Actions Workflow Builder

**Paths in this skill:** `references/*.md` and `scripts/*.py` are relative to this skill's directory. The scripts self-locate the project root by walking up for `agent_actions.yml`, so they work regardless of where invoked from.

## Rules

1. **Every dependency needs at least one field in observe.** Preflight errors otherwise. Even guard-only dependencies need an anchor field.
2. **Every `{{ namespace.field }}` in a prompt needs a matching observe.** Every observe entry feeds the prompt. If the prompt doesn't use it, remove it — you're paying tokens for nothing.
3. **Only observe what the action needs.** Never pass large upstream fields to downstream actions when a distilled version already exists. Context bloat causes LLMs to drift off-topic.
4. **Guard fields must be in observe.** Write `upstream.field == value`, not `field == value`.
5. **Tools receive namespaced data.** Access as `data["action_name"]["field"]`, never `data["field"]`.
6. **Seed data needs no observe.** Use `{{ seed.key }}` directly in prompts.

## Workflow Structure

```
agent_workflow/{name}/
  agent_config/{name}.yml    # workflow config
  agent_io/
    staging/                 # input data (JSON files)
    source/                  # framework-processed input
    store/                   # SQLite DB (state, traces)
    target/                  # per-action output
  seed_data/                 # reference data for grounded prompts
prompt_store/{name}.md       # all prompts for this workflow
schema/{name}/               # output schemas (when complex)
tools/{tool-group}/          # UDF implementations
```

## Config

```yaml
name: my_workflow
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: ollama_cloud
  model_name: gemma4:31b-cloud
  batch_max_workers: 12
  api_key: OLLAMA_API_KEY
  is_operational: true
  data_source:
    type: local
    folder: ./staging
    file_type: [json]
  context_scope:
    seed:
      domain_rules: $file:domain_rules.json
      reference_data: $file:reference_data.json
```

## Data Model

Every record carries a `content` dict that only grows. Each action adds its output under a namespace key:

```
After extract:  content = { "source": {...}, "extract": {...} }
After analyze:  content = { "source": {...}, "extract": {...}, "analyze": {...} }
```

The record is a bus. `context_scope.observe` selects which fields from the bus this action sees.

## References

Detailed guidance — loaded on demand:

- [references/workflow-patterns.md](references/workflow-patterns.md) — 8 harness patterns with YAML
- [references/context-scoping.md](references/context-scoping.md) — observe / passthrough / drop, dependency anchor rule, wildcard vs explicit fields, common mistakes
- [references/loop-patterns.md](references/loop-patterns.md) — verify→rewrite, aggregate threshold patterns, sequential enrichment, contract check loops
- [references/pooling-approach.md](references/pooling-approach.md) — sequential vs parallel pooling, selection action design, pooling vs versioning
- [references/prompt-engineering.md](references/prompt-engineering.md) — one unit of outcome, distil before generating, seed data, output contracts, version diversity

## Action Types

### LLM Action

```yaml
- name: analyze_content
  dependencies: [extract_data]
  guard:
    condition: 'extract_data.is_valid == true'
    on_false: "filter"
  intent: "Analyze extracted data for patterns and insights"
  schema:
    key_findings: string
    confidence_score: integer
    summary: string
  prompt: $my_workflow.Analyze_Content
  context_scope:
    observe:
      - extract_data.structured_output
      - extract_data.metadata
      - source.raw_content
```

The guard depends on `extract_data`, and `extract_data.structured_output` is in observe — that satisfies the dependency anchor rule.

### Tool Action (record mode)

Fan-in tool combining multiple upstream signals:

```yaml
- name: combine_results
  dependencies: [check_quality, verify_accuracy, validate_format]
  kind: tool
  impl: combine_results
  intent: "Combine all checks into a single pass/fail verdict"
  schema: combine_results
  context_scope:
    observe:
      - check_quality.*
      - verify_accuracy.*
      - validate_format.*
```

```python
@udf_tool()
def combine_results(data: dict[str, Any]) -> dict[str, Any]:
    quality = data.get("check_quality", {}) or {}
    accuracy = data.get("verify_accuracy", {}) or {}
    issues = []
    if not quality.get("passed"):
        issues.append(quality.get("reason", "quality check failed"))
    return {"has_failures": len(issues) > 0, "combined_issues": "\n".join(issues)}
```

### Tool Action (file mode)

File-mode tools receive all records as a list. Use for dedup, batching, aggregation:

```yaml
- name: deduplicate
  dependencies: [enrich_records]
  kind: tool
  impl: deduplicate_records
  schema: deduplicate_records
  granularity: File
  context_scope:
    observe: [enrich_records.*]
```

```python
@udf_tool(granularity=Granularity.FILE)
def deduplicate_records(data: list[dict]) -> list[dict]:
    seen, result = set(), []
    for item in data:
        key = item["enrich_records"]["canonical_id"]
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
```

Return rules:
- Returning input items (filter/enrich): `list[dict]` — TrackedItem provenance automatic
- Constructing new dicts (merge/expand): `FileUDFResult(outputs=[{"source_index": i, "data": {...}}])`

### Versioned Action + Merge

3 independent evaluators, then a tool checks consensus:

```yaml
- name: evaluate
  dependencies: [prepare_input]
  versions: { param: evaluator_id, range: [1, 2, 3], mode: parallel }
  intent: "Independently evaluate the input"
  schema:
    verdict: string
    reasoning: string
  prompt: $my_workflow.Evaluate
  context_scope:
    observe:
      - prepare_input.question
      - prepare_input.options

- name: aggregate_evaluations
  dependencies: [evaluate]
  kind: tool
  impl: aggregate_evaluations
  version_consumption: { source: evaluate, pattern: merge }
  intent: "Check if evaluators agree"
  schema:
    consensus: boolean
    agreement_count: integer
    final_verdict: string
  context_scope:
    observe:
      - evaluate.*
      - prepare_input.expected_answer
```

Version merge tools receive double-nested data:
```python
v1 = data["evaluate_1"]["evaluate_1"]["verdict"]
v2 = data["evaluate_2"]["evaluate_2"]["verdict"]
v3 = data["evaluate_3"]["evaluate_3"]["verdict"]
```

In prompts, use `{{ version.i }}`, `{{ version.length }}`, `{{ version.first }}`, `{{ version.last }}` — bare `{{ i }}` crashes with `'i' is undefined`.

### Guard + Conditional Rewrite

Only rewrite if checks failed:

```yaml
- name: rewrite_output
  dependencies: [combine_results, original_output]
  guard:
    condition: 'combine_results.has_failures == true'
    on_false: "skip"
  intent: "Rewrite output fixing all issues"
  context_scope:
    observe:
      - original_output.*
      - combine_results.combined_issues
```

`filter` removes the record entirely. `skip` sets `content["action_name"] = null` and the record continues — downstream must handle null with `{% if %}` in prompts.

### HITL (Human-in-the-Loop)

```yaml
- name: human_review
  dependencies: [generate_output]
  kind: hitl
  granularity: file
  intent: "Human reviews output before final processing"
  hitl:
    port: 3001
    timeout: 3600
  context_scope:
    observe:
      - generate_output.*

- name: next_step
  dependencies: [human_review]
  guard:
    condition: 'human_review.hitl_status == "approved"'
    on_false: "filter"
  context_scope:
    observe:
      - human_review.*
```

## Prompts

Stored in `prompt_store/{workflow}.md`. Referenced as `$workflow_name.Prompt_Name`.

```markdown
{prompt Analyze_Content}
You are a domain expert. Analyze the following data.

## INPUT DATA

{{ extract_data.structured_output }}

{% if previous_analysis.summary %}
## PRIOR ANALYSIS
{{ previous_analysis.summary }}
{% endif %}

## REFERENCE
{{ seed.domain_rules.key_principle }}

## OUTPUT
```json
{
  "key_findings": "...",
  "confidence_score": 8,
  "summary": "..."
}
```
{end_prompt}
```

Every `{{ namespace.field }}` must have a matching observe entry. Use `{% if %}` for fields that may be null (from skipped guards).

## Context Scope

| Directive | LLM sees? | On bus? | Use for |
|-----------|:---------:|:-------:|---------|
| `observe` | Yes | Yes | Data the action needs |
| `passthrough` | No | Yes | Forward to downstream without tokens |
| `drop` | No | Yes (hidden) | Hide from this action's LLM context without removing from the bus |

See [references/context-scoping.md](references/context-scoping.md) for the dependency anchor rule, wildcard vs explicit, and the common mistakes.

## Schemas

```yaml
# Inline — for simple output
schema:
  verdict: string
  score: integer
  reasoning: string

# File reference — for complex schemas at schema/{workflow}/{action}.yml
schema: action_name
```

## Running Workflows

All commands run from the **project root** (where `agent_actions.yml` lives). `-u tools` is required whenever the workflow has UDFs.

```bash
# Setup
uv sync

# Validate all impl: references resolve to real @udf_tool functions before running
agac validate-udfs -a {workflow} -u tools

# Run (resumes from last completed action)
agac run -a {workflow} -u tools

# Fresh run (clears all state first)
agac run -a {workflow} -u tools --fresh

# Per-record status across all actions
agac dispositions -a {workflow} -u tools
```

Use `record_limit: N` on the first action in the YAML to test cheaply on a subset of source records.

`retry` and `reprompt` are separate concerns — keep them distinct:
```yaml
retry:
  enabled: true
  max_attempts: 3        # retries on transient errors: network, rate limits, timeouts

reprompt:                # in defaults — applies to LLM actions only
  on_schema_mismatch: reprompt
  max_attempts: 3        # retries when LLM output fails schema validation
  use_self_reflection: true
  on_exhausted: return_last
```

## Debugging

**Quick prompt inspection without querying the DB:** set `prompt_debug: true` on the action in the YAML — the framework logs the full rendered prompt with resolved context to stdout during the run. Set it back to `false` after.

**When output is wrong but pipeline didn't crash:**
1. Namespace names match exactly? Typos cause empty data, not errors.
2. Guard references an existing field? Missing field evaluates to None — may silently filter all records.
3. Tool accessing `data["namespace"]["field"]` not `data["field"]`?
4. Version merge tool unwrapping double nesting? `data["action_1"]["action_1"]["field"]`
5. Schema fields match what the LLM/tool returns? Extra fields are silently dropped.
6. Is a large upstream field (e.g. full page content) polluting a downstream action? Check if a distilled field already carries what you need.

**Tracing records across actions:**
Records carry `version_correlation_id` — same ID across all actions for the same source record. Use `prompt_trace` table for rendered prompts and `target_data` for outputs. Correlate by `target_id` or `version_correlation_id`, not by array index.

**Inspecting an action's config, context, and schema:**

```bash
# Action config, dependencies, observe fields, output schema + template variable resolution
python3 scripts/inspect_action.py {workflow} {action_name}

# All action schemas (input → output) in one table
agac schema -a {workflow} -u tools

# Full pipeline graph
agac inspect -a {workflow} -u tools
```

**Inspecting live output data and rendered prompts:**

Use `agac preview` — backend-agnostic, works regardless of store type:

```bash
agac preview -w {workflow}                          # list actions with data
agac preview -w {workflow} -a {action_name}         # records for one action
agac preview -w {workflow} -a {action_name} -f json # JSON format
agac preview -w {workflow} --stats                  # storage stats
```

> `agac preview` is currently broken ("Backend not initialized"). See `spec/cli_issues_agac.md`. Do not work around it with backend-specific raw queries — fix the CLI instead.

**Resetting state:**

```bash
# Soft reset: clears agent_status so next run starts from scratch (keeps DB)
python3 scripts/reset_workflow.py {workflow}

# Full reset: wipes source, store, target, and status
python3 scripts/reset_workflow.py {workflow} --full
```


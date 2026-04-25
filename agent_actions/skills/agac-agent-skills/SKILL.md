---
name: agac
description: Build, configure, and debug agent-actions agentic workflows. Trigger on workflow YAML, UDFs, context_scope, guards, versions, schemas, seed data, prompts, reprompt, HITL, cross-workflow chaining, or debugging empty/filtered/mismatched output.
---

# Agent Actions Workflow Builder

## How It Works

1. **Dependencies + observe go together.** When you add a dependency, add its fields to `context_scope.observe`. Fan-in actions observe from ALL branch dependencies.
2. **Prompt references = observe entries.** Every `{{ namespace.field }}` in a prompt needs a matching observe. Every observe feeds the prompt.
3. **Observe = what the LLM sees = tokens you pay for.** Only observe what the prompt uses. Wildcards (`.*`) are expensive — prefer specific fields.
4. **Seed data is auto-available in prompts** via `{{ seed.key }}`. No observe entry needed for LLM actions. Tool UDFs receive seed via kwargs.
5. **All field references use namespace.field format.** In observe, passthrough, drop, and guard conditions: `aggregate_votes.filter`, not `filter`. Preflight validates this.
6. **Guard conditions use the same namespace.field paths.** `aggregate_votes.filter == "keep"`, not `filter == "keep"`.
7. **Fan-in: list all converging branches in dependencies AND observe.** The bus carries everything — you just tell the action what to look at.

## Data Model (Additive Bus)

Every record carries a `content` dict that **only grows**. Each action adds its output under a namespace key. Nothing is ever removed.

```
After action A: content = { "source": {...}, "A": {...} }
After action B: content = { "source": {...}, "A": {...}, "B": {...} }
After action C: content = { "source": {...}, "A": {...}, "B": {...}, "C": {...} }
```

The record is a **bus** — it carries all namespaces so any downstream action can reach back to any upstream. `context_scope.observe` is the **selector** — it picks exactly which fields this action needs. The bus is storage; observe is access control.

## Record Mode Tools

Tools receive **observe-filtered namespaced data** — fields nested under the producing action's name. The framework handles all provenance, wrapping, and upstream preservation.

```python
@udf_tool()
def my_tool(data: dict[str, Any]) -> dict:
    # Access fields by namespace
    claims = data["extract_claims"]["factual_claims"]
    score = data["aggregate_scores"]["consensus_score"]

    return {"summary": f"Score {score}, {len(claims)} claims"}
```

**Version merge tools** receive version-namespaced data. Each version's output is under its versioned name:
```python
# Access each voter's score
score_1 = data["score_quality_1"]["score_quality_1"]["helpfulness_score"]
score_2 = data["score_quality_2"]["score_quality_2"]["helpfulness_score"]
score_3 = data["score_quality_3"]["score_quality_3"]["helpfulness_score"]
avg = (score_1 + score_2 + score_3) / 3
```

**Data access pattern — fields are always namespaced:**
```python
# Access fields by the action that produced them
question = data["write_scenario_question"]["question_text"]
answer = data["consolidate_answer_from_source"]["final_answer_text"]
score = data["aggregate_scores"]["consensus_score"]
```

## FILE Mode Tools

FILE mode tools receive **clean business dicts** — no framework fields. Each item is a `TrackedItem` (dict subclass with hidden provenance). Treat as normal dicts.

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult

@udf_tool(granularity=Granularity.FILE)
def assign_batch(data: list[dict], batch_size: int = 50) -> FileUDFResult:
    """N→N: add a field to every record."""
    return FileUDFResult(outputs=[
        {"source_index": i, "data": {**item, "batch": f"b_{i // batch_size}"}}
        for i, item in enumerate(data)
    ])

@udf_tool(granularity=Granularity.FILE)
def deduplicate(data: list[dict]) -> list[dict]:
    """N→M filter: return subset. TrackedItem provenance automatic."""
    seen, deduped = set(), []
    for item in data:
        key = item["question_text"]
        if key not in seen:
            seen.add(key)
            deduped.append(item)  # returning TrackedItem — provenance preserved
    return deduped
```

**Return rules:**
- **Passthrough/filter/enrich** (return input items): return `list[dict]` — TrackedItem provenance automatic
- **Merge/expand** (construct NEW dicts): return `FileUDFResult` with `source_index` per output
- **Plain dict in list return → `ValueError`** — framework can't trace provenance

## Context Scope

| Directive | LLM sees? | In output? | Use for |
|-----------|:---------:|:----------:|---------|
| `observe` | Yes | No | Data the action processes |
| `passthrough` | No | Yes | Fields downstream needs (zero tokens) |
| `drop` | No | No | Noise reduction (data stays on bus) |

## Guards

Guards use **dotted namespace paths**:

```yaml
guard:
  condition: 'aggregate_scores.consensus_score >= 6'
  on_false: "filter"    # filter = remove record | skip = null namespace
```

| `on_false` | Record | Namespace | Downstream |
|-----------|--------|-----------|------------|
| `filter` | Removed from pipeline | None created | No processing |
| `skip` | Survives | `action_name: null` | Runs, must handle null |

## Versions (Parallel Voting)

```yaml
- name: score_quality
  versions: { param: scorer_id, range: [1, 2, 3], mode: parallel }

- name: aggregate
  dependencies: [score_quality]
  kind: tool
  impl: aggregate_tool
  version_consumption: { source: score_quality, pattern: merge }
  context_scope:
    observe: [score_quality.*]   # resolver expands to _1, _2, _3
```

In prompts, version context is under `{{ version.i }}`, `{{ version.length }}`, `{{ version.first }}`, `{{ version.last }}`.

## Fan-In Pattern

When parallel branches rejoin — just observe from both. The bus has everything:

```yaml
- name: merge_point
  dependencies: [branch_a_end, branch_b_end]
  context_scope:
    observe:
      - branch_a_end.*
      - branch_b_end.*
```

No merge operator needed. `dependencies` controls when, `observe` controls what.

## Seed & Prompts

```yaml
defaults:
  context_scope:
    seed_path:
      rules: $file:rules.json
```

Prompts: `{{ seed.rules.field }}`. Config key is `seed_path:`, reference prefix is `seed.`.

```markdown
{prompt My_Prompt}
Content: {{ source.page_content }}
Rules: {{ seed.rules.key }}
Prior analysis: {{ summarize_page_content.summary }}
{end_prompt}
```

## Schemas

Always define properties. `type: object` without properties = `additionalProperties: false`.

```yaml
# Inline (simple)
schema: { vote: string, score: integer, reasoning: string }

# File (complex) — schema/{workflow}/{action}.yml
type: object
properties:
  vote: { type: string, enum: ["keep", "filter"] }
  score: { type: integer, minimum: 1, maximum: 10 }
additionalProperties: false
```

## Non-JSON Mode

For models that can't produce JSON. Each action outputs one plain-text field:

```yaml
- name: classify_issue
  json_mode: false
  output_field: issue_type
```

Result: `content["classify_issue"]["issue_type"] = "plain text value"`

## Adding a New Action

When asked to add an action, use these templates. All fields with comments need to be filled in.

**LLM action:**
```yaml
  - name: my_action                         # ← rename
    dependencies: [previous_action]          # ← runs after this action
    intent: "What this action does"          # ← one sentence

    # Schema: output fields (namespaced under action name automatically)
    schema:
      field_name: string                     # ← define output fields
      # other_field: { type: array, items: { type: string } }

    # Prompt: must match a heading in prompt_store/{workflow}.md
    prompt: $workflow_name.My_Action_Prompt   # ← create matching prompt

    # Context Scope: what this action sees from upstream
    context_scope:
      observe:
        - previous_action.field_name         # ← namespace.field for each prompt reference
        # - source.raw_input_field           # ← original input data
      # passthrough:                         # ← carry forward without using tokens
      #   - previous_action.some_field
      # drop:                               # ← exclude from prompt context
      #   - previous_action.verbose_field

    # Optional:
    # guard: { condition: "field == 'value'", on_false: skip }
    # retry: { enabled: true, max_attempts: 3 }
    # record_limit: 5                       # ← limit for testing
```

**Record tool action:**
```yaml
  - name: my_tool
    dependencies: [previous_action]
    kind: tool
    impl: my_tool_name                       # ← tools/{workflow}/my_tool_name.py
    intent: "What this tool does"
    schema:
      output_field: string                   # ← define output fields
    context_scope:
      observe:
        - previous_action.*                  # ← tool receives these fields
```

With matching tool file at `tools/{workflow}/my_tool_name.py`:
```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def my_tool_name(data: dict[str, Any]) -> dict[str, Any]:
    """What this tool does."""
    # Data arrives namespaced: data["previous_action"]["field_name"]
    value = data["previous_action"]["field_name"]
    return {"output_field": value}
```

**FILE tool action** (processes entire array at once):
```yaml
  - name: my_file_tool
    dependencies: [previous_action]
    kind: tool
    impl: my_file_tool_name                  # ← tools/{workflow}/my_file_tool_name.py
    granularity: File
    intent: "What this tool does with the full array"
    schema:
      output_field: string
    context_scope:
      observe:
        - previous_action.*
```

With matching tool file:
```python
from typing import Any
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def my_file_tool_name(data: list[dict[str, Any]]) -> list[dict]:
    """Processes entire array. Return input items for automatic provenance."""
    result = []
    for item in data:
        # Filter, enrich, or transform items
        result.append(item)  # returning TrackedItem preserves provenance
    return result
```

## Debugging

```bash
agac run -a workflow          # Run
agac run -a workflow --fresh  # Clear state and re-run
agac render -a workflow       # Compiled YAML (resolve Jinja/schemas/versions)
```

Check errors: `events.json`. Use `record_limit: 2` to test cheaply.

Full reset:
```bash
rm -rf agent_io/target agent_io/.agent_status.json agent_io/source agent_io/store
mkdir -p agent_io/target
```

## Agentic Patterns

All driven by the same data model: `RecordEnvelope` builds the bus, `context_scope` controls access. Here's how to configure each pattern.

### Linear Chain

Each action observes the previous. Content accumulates on the bus.

```yaml
  - name: extract
    prompt: $workflow.Extract

  - name: analyze
    dependencies: [extract]
    context_scope:
      observe: [extract.key_facts]
    prompt: $workflow.Analyze

  - name: summarize
    dependencies: [analyze]
    context_scope:
      observe: [extract.key_facts, analyze.analysis]
    prompt: $workflow.Summarize
```

### Map-Reduce

1→N split (Record tool) then N→1 aggregate (FILE tool).

```yaml
  - name: split_into_chunks          # 1 record → N records
    kind: tool
    impl: split_document
    granularity: Record

  - name: analyze_chunk              # process each independently
    dependencies: [split_into_chunks]
    context_scope:
      observe: [split_into_chunks.*]
    prompt: $workflow.Analyze_Chunk

  - name: aggregate_results          # see ALL chunks at once
    dependencies: [analyze_chunk]
    kind: tool
    impl: aggregate_analyses
    granularity: File                 # ← FILE mode: receives entire array
    context_scope:
      observe: [analyze_chunk.*]
```

### Parallel Voting (Consensus)

Multiple LLM evaluations merged into one. Each voter gets the same input but responds independently.

```yaml
  - name: score_quality
    dependencies: [previous_action]
    versions: { param: voter_id, range: [1, 2, 3], mode: parallel }
    prompt: $workflow.Score_Quality
    context_scope:
      observe: [previous_action.*]

  - name: aggregate_scores
    dependencies: [score_quality]
    kind: tool
    impl: aggregate_votes
    version_consumption: { source: score_quality, pattern: merge }
    context_scope:
      observe: [score_quality.*]      # resolver expands to _1, _2, _3
```

### Fan-Out / Fan-In

Parallel branches that rejoin. The bus carries everything — the converging action just observes both.

```yaml
  # Two branches from same parent
  - name: branch_a
    dependencies: [shared_parent]
    context_scope:
      observe: [shared_parent.*]

  - name: branch_b
    dependencies: [shared_parent]
    context_scope:
      observe: [shared_parent.*]

  # Convergence point — observes from both branches
  - name: combine
    dependencies: [branch_a, branch_b]
    context_scope:
      observe:
        - branch_a.result
        - branch_b.result
```

### Grounded Retrieval (LLM → Tool → LLM)

LLM generates search criteria, tool retrieves candidates, LLM ranks results.

```yaml
  - name: generate_search
    prompt: $workflow.Generate_Search
    schema: { search_query: string, filters: array }

  - name: retrieve_candidates
    dependencies: [generate_search]
    kind: tool
    impl: search_database
    context_scope:
      observe: [generate_search.*]

  - name: rank_results
    dependencies: [retrieve_candidates]
    context_scope:
      observe:
        - generate_search.search_query
        - retrieve_candidates.candidates
    prompt: $workflow.Rank_Results
```

### Guard Gates (Conditional Execution)

```yaml
  - name: generate_response
    dependencies: [score_quality]
    guard:
      condition: 'aggregate_scores.consensus_score >= 6'
      on_false: filter              # filter = remove record entirely
    context_scope:
      observe: [aggregate_scores.*]
    prompt: $workflow.Generate_Response

  - name: rewrite_if_needed
    dependencies: [validate]
    guard:
      condition: 'validate.pass == false'
      on_false: skip                # skip = null namespace, record continues
    context_scope:
      observe: [validate.violations, original_draft.*]
    prompt: $workflow.Rewrite
```

### HITL (Human-in-the-Loop)

Human reviews AI output. Decision stored under the HITL action's namespace.

```yaml
  - name: ai_assessment
    prompt: $workflow.AI_Assessment

  - name: human_review
    dependencies: [ai_assessment]
    kind: hitl
    granularity: file
    hitl:
      port: 3001
      timeout: 3600
    context_scope:
      observe: [ai_assessment.*]

  - name: next_step
    dependencies: [human_review]
    context_scope:
      observe: [human_review.decision]
```

### Reprompt Validation

LLM output checked by a UDF. If validation fails, LLM is re-prompted with the error.

```yaml
  - name: write_description
    dependencies: [previous_action]
    reprompt:
      validation: check_word_count   # tools/{workflow}/check_word_count.py
      max_attempts: 3
      on_exhausted: return_last      # return_last | raise
    prompt: $workflow.Write_Description
```

The validation UDF returns `{"valid": true}` or `{"valid": false, "feedback": "Too short"}`.

### Cross-Workflow Chaining

Workflow B consumes output from Workflow A. All namespaces cross the boundary.

```yaml
# In workflow B's config:
upstream_workflows:
  - workflow: workflow_a
    actions: [final_action]          # which actions to import
```

### Passthrough Routing (Zero-Token Forwarding)

Carry fields downstream without putting them in the prompt (saves tokens).

```yaml
  context_scope:
    observe:
      - extract.key_facts             # LLM sees this (costs tokens)
    passthrough:
      - extract.raw_source            # forwarded but NOT in prompt (free)
    drop:
      - extract.debug_info            # excluded from everything
```

### Summary Table

| # | Pattern | Key Config |
|---|---------|------------|
| 1 | Linear chain | `dependencies` + `observe` previous |
| 2 | Map-Reduce | Record tool (1→N) + `granularity: File` tool (N→1) |
| 3 | Parallel voting | `versions` + `version_consumption: merge` |
| 4 | Parallel generation | Same as voting, pick best in consumer |
| 5 | Fan-out / Fan-in | Multiple `dependencies`, observe from all branches |
| 6 | LLM/Tool alternation | Alternate `kind: tool` and LLM actions |
| 7 | Grounded retrieval | LLM → tool search → LLM rank |
| 8 | Guard gates | `guard.on_false: filter` or `skip` |
| 9 | HITL | `kind: hitl`, `granularity: file` |
| 10 | Cross-workflow | `upstream_workflows` config |
| 11 | Context isolation | `drop` directive in context_scope |
| 12 | Reprompt validation | `reprompt.validation` UDF |
| 13 | Non-JSON field-by-field | `json_mode: false`, `output_field` |
| 14 | 1→N flatten | Record tool returns `list[dict]` |
| 15 | Passthrough routing | `passthrough` in context_scope |

## References

- **[UDF Reference](references/udf-reference.md)** — Record mode, FILE mode, TrackedItem, FileUDFResult
- **[Context Scope](references/context-scope-guide.md)** — observe/drop/passthrough, resolution
- **[Workflow Patterns](references/workflow-patterns.md)** — fan-in, diamond, ensemble, map-reduce
- **[Framework Contracts](references/framework-contracts.md)** — the 20 rules
- **[Guards](references/guards.md)** — skip vs filter, conditions, namespace effects
- **[Debugging Guide](references/debugging-guide.md)** — triage checklist
- **[YAML Schema](references/yaml-schema.md)** — complete config reference
- **[Prompt Patterns](references/prompt-patterns.md)** — template syntax, seed access
- **[Schema Design](references/schema-design-guide.md)** — output schemas
- **[Reprompt Patterns](references/reprompt-patterns.md)** — validation retry
- **[Aggregation Patterns](references/aggregation-patterns.md)** — version merge, reduce_key
- **[HITL Patterns](references/hitl-patterns.md)** — human-in-the-loop
- **[CLI Reference](references/cli-reference.md)** — agac commands
- **[Data Flow Patterns](references/data-flow-patterns.md)** — record lifecycle

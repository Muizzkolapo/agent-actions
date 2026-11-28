---
name: agac-agent-skills
description: Build, run, inspect, and debug agent-actions workflows. Triggers on workflow YAML, UDFs, observe/passthrough/drop, guards, versions, schemas, seed data, prompts, HITL, running or resetting a pipeline, debugging empty/filtered output, sandbox, offline, mock, scenario, sandbox.yml, stub, chaos, sandbox check, sandbox_expected.yml, the sandbox starter template, testing a workflow without an API key, knowledge bases, knowledge:, context_scope.retrieve, retrieval, RAG, citations, or agac knowledge.
---

# Agent Actions Workflow Builder

**Paths in this skill:** `references/*.md` and `scripts/*.py` are relative to this skill's directory. The scripts self-locate the project root by walking up for `agent_actions.yml`, so they work regardless of where invoked from.

## Rules

1. **Every dependency needs at least one field in observe.** Preflight errors otherwise. Even guard-only dependencies need an anchor field.
2. **Every action named in observe, a prompt or a guard must be upstream through `dependencies`.** Naming it does not wire it in; preflight refuses it otherwise. An action with no `dependencies` reads only the staged input, and a version merge depends on its base name.
3. **Every `{{ namespace.field }}` in a prompt needs a matching observe.** Every observe entry feeds the prompt. If the prompt doesn't use it, remove it — you're paying tokens for nothing.
4. **Only observe what the action needs.** Never pass large upstream fields to downstream actions when a distilled version already exists. Context bloat causes LLMs to drift off-topic.
5. **Guard fields carry their action's name.** Write `upstream.field == value`, not `field == value`. A guard reads the record as stored, so the field does not have to be in observe; observing it only to guard on it sends it to the model for nothing.
6. **A record tool reads by action name; a FILE tool reads flat keys.** A record tool gets `data["action_name"]["field"]`, one level, version merges included. A FILE tool gets a list of items holding the observed fields as flat keys: `item["field"]` for a field named in observe, and `item["action_name.field"]` only where two observed names really collide (two named fields with one name, or a wildcard field with the same name as a named field, which keeps the bare key).
7. **Seed data needs no observe.** Use `{{ seed.key }}` directly in prompts. `{{ retrieve.<entry>.matches }}` needs none either: the load adds the search step to the dependencies and the observe (see [references/knowledge-retrieval.md](references/knowledge-retrieval.md)).
8. **Test offline first.** After each change, run `agac run -w {workflow} -u tools --sandbox` before a real run. The offline mock answers every LLM action, with no API key and no cost, and the run checks the wiring. To pin what the run must produce, write `sandbox_expected.yml` and run `agac sandbox check -w {workflow}`. See [references/sandbox-testing.md](references/sandbox-testing.md).

## Workflow Structure

```
agent_workflow/{name}/
  agent_config/{name}.yml    # workflow config
  agent_io/
    staging/                 # input data (JSON files)
    store/                   # SQLite DB (state, traces)
    target/                  # per-action output
    sandbox/                 # output of sandbox runs (agac run --sandbox)
  seed_data/                 # reference data for grounded prompts
prompt_store/{name}.md       # all prompts for this workflow
schema/{name}/               # output schemas (when complex)
tools/{tool-group}/          # UDF implementations
sandbox.yml                  # optional scenario of sandbox runs
sandbox.{name}.yml           # optional scenario of this workflow only; read before sandbox.yml
sandbox_expected.yml         # optional outcomes that agac sandbox check asserts
sandbox_expected.{name}.yml  # optional outcomes of this workflow only; read before sandbox_expected.yml
knowledge/{base}/             # optional source files of a knowledge base (agent_actions.yml knowledge:)
.agac/knowledge/             # built knowledge indexes; keep .agac/ in .gitignore
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

To read input rows from a database instead of `staging/`, set `data_source: {type: database, connection: <name>, sql: <query>}`; to write an action's results to a table, add a top-level `outputs:` block. Connections are named in `agent_actions.yml`, with credentials as `${NAME}`. See [references/database-io.md](references/database-io.md).

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
- [references/database-io.md](references/database-io.md) — `connections:`, a `database` data source and its snapshot, `outputs:` tables and their modes, `--refresh-input`, `agac export`
- [references/knowledge-retrieval.md](references/knowledge-retrieval.md) — seed or retrieve, `knowledge:` bases in `agent_actions.yml` (sources, `index`, `chunk_config`), `context_scope.retrieve` (methods, `where`, limits), the `<action>__<entry>` step, the prompt with citations, `agac knowledge`, the change warning and `--rerun`
- [references/sandbox-testing.md](references/sandbox-testing.md) — `agac run --sandbox`, what the mock answers, the `sandbox.yml` scenario (faults, `pin`, tool `stub`), presets, the starter template, `agac sandbox check` and `sandbox_expected.yml`, testing recipes, limits

Related skills:

- `agac-operations` — run a large workflow, recover it without paying twice, and check its output counts
- `agac-expectations` — `expect:` rules, judges and their calibration
- `agac-blind-verification` — verifiers that never see the reference

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

The guard reads `extract_data.is_valid` without observing it: a guard reads any field of an upstream action. `extract_data.structured_output` is in observe, which satisfies the dependency anchor rule.

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

File-mode tools receive all records as a list. Each item holds the observed fields as flat keys, with no action name around them. Use for dedup, batching, aggregation:

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
        key = item["canonical_id"]
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
```

A field named in `observe` is under its bare name. A key is `action_name.field` only where two observed names really collide: two named fields with one name, a wildcard field with the same name as a named field, or several actions observed by wildcard (`item["evaluate_1.verdict"]`).

Return rules:
- Returning input items (filter/enrich): `list[dict]` — TrackedItem provenance automatic
- Constructing new dicts (merge/expand): `FileUDFResult(outputs=[{"source_index": i, "data": {...}}])`
  - `source_index` names which input produced the row: a position, a list of them for a many-to-one output, or `None` when no single input did. A position is a non-negative built-in `int` — cast a numpy/pandas index with `int()`. A negative one, a bool, or a `None` inside the list is refused.

### Versioned Action + Merge

3 independent evaluators, then a tool checks consensus:

```yaml
- name: evaluate
  dependencies: [prepare_input]
  versions: { param: evaluator_id, range: [1, 2, 3]}
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

A version merge tool reads each version under its own name, one level deep like any record tool:
```python
v1 = data["evaluate_1"]["verdict"]
v2 = data["evaluate_2"]["verdict"]
v3 = data["evaluate_3"]["verdict"]
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

### MCP Action (a tool of an MCP server)

Call one tool of an MCP server for each record, with no Python tool. Declare the server once in `agent_actions.yml`:

```yaml
mcp_servers:
  dbt:
    command: uvx
    args: [dbt-mcp]
    env: { DBT_TOKEN: "${DBT_TOKEN}" }   # read from the environment, never written here
```

```yaml
- name: lineage
  kind: mcp
  server: dbt
  tool: get_lineage
  schema: lineage_output                 # required, as for a tool action
  arguments:
    model: source.model_name             # field reference: added to observe
    depth: { value: 2 }                  # constant
```

It routes as a RECORD tool action: online, one call a record, no `prompt`, no `impl`, no File granularity. A tool error fails the record. A sandbox run starts no server and the mock answers from the schema, unless the scenario sets `stub: false` on the action.

### HITL (Human-in-the-Loop)

```yaml
- name: human_review
  dependencies: [generate_output]
  kind: hitl
  granularity: file
  intent: "Human reviews output before final processing"
  hitl:
    instructions: "Check each output and approve or reject it"
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

Every `{{ namespace.field }}` must have a matching observe entry. Observe a field that may be null (from a skipped guard) as optional (`namespace.field?`) and wrap its use in `{% if %}`.

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
agac validate-udfs -w {workflow} -u tools

# Run (resumes from last completed action)
agac run -w {workflow} -u tools

# Fresh run (clears all state first)
agac run -w {workflow} -u tools --fresh

# Sandbox run: the offline mock answers every LLM action (no API key, no cost)
agac run -w {workflow} -u tools --sandbox

# Sandbox run with faults, to test retry and repair
agac run -w {workflow} -u tools --sandbox --scenario chaos

# Sandbox run checked against sandbox_expected.yml (exit 0 pass, 1 mismatch, 2 bad file)
agac sandbox check -w {workflow} -u tools

# A starter project that uses each feature once, and passes its check offline
agac init my_sandbox --template sandbox

# Per-record status across all actions
agac dispositions -w {workflow} -u tools

# Model calls and tokens per action, with an estimated cost if agent_actions.yml has prices:
agac usage -w {workflow}
```

Use `record_limit: N` on any action in the YAML to test cheaply on a subset of its records — on the first action to shrink the whole run, further down to shrink one step. To shrink a run without editing the YAML, pass `--record-limit N` or `--file-limit N` to `agac run`, or set `AGAC_RECORD_LIMIT` / `AGAC_FILE_LIMIT` — the first bounds records per input file, the second how many files are walked.

To test with no cost at all, add `--sandbox` to `agac run`. The offline mock answers every LLM action, and the output goes to `agent_io/sandbox/`, apart from real runs. Give `--sandbox` to `agac status`, `records`, `traces`, `dispositions` and `preview` to read it. See [references/sandbox-testing.md](references/sandbox-testing.md).

`retry` and `expect` are separate concerns — keep them distinct:
```yaml
retry:
  enabled: true
  max_attempts: 3        # retries on transient errors: network, rate limits, timeouts

expect:                  # in defaults — applies to LLM actions only
  repair: auto           # regenerate with the failure detail when a rule fails
  structural: auto       # send the schema feedback when the response does not conform
  max_iterations: 3      # counting the first generation
  on_exhausted: return_last
```

## Debugging

**Quick prompt inspection without querying the DB:** set `prompt_debug: true` on the action in the YAML — the framework logs the full rendered prompt with resolved context to stdout during the run. Set it back to `false` after.

**When output is wrong but pipeline didn't crash:**
1. Namespace names match exactly? Typos cause empty data, not errors.
2. Guard references an existing field? Missing field evaluates to None — may silently filter all records.
3. Record tool accessing `data["namespace"]["field"]`? FILE tool accessing the flat `item["field"]` (or `item["namespace.field"]`)?
4. Version merge tool reading each version by its own name? `data["action_1"]["field"]`, one level.
5. Schema fields match what the LLM/tool returns? Extra fields are silently dropped.
6. Is a large upstream field (e.g. full page content) polluting a downstream action? Check if a distilled field already carries what you need.

**Tracing records across actions:**
`agac dispositions -w {workflow} --record {source_guid}` follows one record through every action in run order: its disposition and reason at each, the actions it never reached, and the guard that filtered or skipped it. Start there when a record is missing from an action's output.
Records carry `version_correlation_id` — same ID across all actions for the same source record. Use `agac traces -w {workflow} -A {action}` for rendered prompts and `agac records -w {workflow} -A {action}` for stored outputs (the store keeps both compressed, so `sqlite3` shows blobs). Correlate by `target_id` or `version_correlation_id`, not by array index.

**Inspecting an action's config, context, and schema:**

```bash
# Action config, dependencies, observe fields, output schema + template variable resolution
python3 scripts/inspect_action.py {workflow} {action_name}

# All action schemas (input → output) in one table
agac schema -w {workflow} -u tools

# Full pipeline graph
agac inspect -w {workflow} -u tools
```

**Inspecting live output data and rendered prompts:**

Use `agac preview` — backend-agnostic, works regardless of store type:

```bash
agac preview -w {workflow}                          # list actions with data
agac preview -w {workflow} -A {action_name}         # records for one action
agac preview -w {workflow} -A {action_name} -f json # JSON format
agac preview -w {workflow} --stats                  # storage stats
```

**Resetting state:**

```bash
# Soft reset: clears agent_status so next run starts from scratch (keeps DB)
python3 scripts/reset_workflow.py {workflow}

# Full reset: wipes target, status, the store (all but its run lock file) and
# the output of sandbox runs (agent_io/sandbox/),
# and reclaims what a provider recorded locally about this workflow's batches (the
# store is what names them). It exits while a run of the workflow is in progress
# (with a plain python3 on Windows it cannot check, and only warns).
python3 scripts/reset_workflow.py {workflow} --full
```


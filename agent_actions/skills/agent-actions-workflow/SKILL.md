---
name: agent-actions-workflow
description: Build, configure, and debug agent-actions agentic workflows. Use this skill whenever the user works with workflow YAML configs, writes UDF tool functions, configures context_scope (observe/passthrough/drop), sets up guards, versions, schemas, seed data, prompt templates, reprompt validation, batch mode, HITL actions, reduce_key aggregation, or cross-workflow chaining (upstream declarations, --downstream/--upstream flags). Also trigger when debugging pipeline output — empty records, guard filtering issues, schema mismatches, unexpected action results, caching problems, or stale re-runs. Trigger on CLI questions about agac run, agac render, agac validate-udfs, or agac batch. Even if the user just says "add an action", "why is my output empty", "my UDF returns None", "records are being filtered", "chain workflows", or "run downstream", this skill applies.
---

# Agent Actions Workflow Builder

## Understanding the Pipeline First

agent-actions handles data plumbing implicitly, like Terraform handles state:
- You don't manage data flow between actions — `context_scope` declares it
- You don't track record provenance — `lineage` handles it
- You don't orchestrate execution order — `dependencies` handles it
- You don't write vendor-specific LLM code — `model_vendor` abstracts it

Your job: define WHAT each action does and WHAT data it needs. The framework handles HOW.

Before changing anything, read the workflow YAML and check what the upstream action actually produces (`cat agent_io/target/<parent>/sample.json`). Most bugs come from mismatched expectations between actions.

```bash
agac run -a my_workflow              # Run workflow
agac render -a my_workflow           # Compiled YAML (schemas inlined, versions expanded)
```

## How Data Flows

```
Source record
  → Framework adds source_guid, node_id, lineage
    → observe selects which namespaces the action can read from the record
      → LLM/tool receives observed fields (namespaced by action name)
        → Tool processes and returns result
          → passthrough fields merge into output
            → Output stored under this action's namespace
              → Next action's observe selects from the record's namespaces
```

Once you understand this chain, most issues become obvious:
- UDF gets None for a field? Fields are namespaced — access with `data["action_name"]["field"]`, not `data.get("field")`. In FILE mode, read from `record["content"]["action_name"]["field"]`
- Downstream can't see a field? It wasn't in `observe` or `passthrough` — only `observe` namespaces reach the LLM, `passthrough` namespaces reach the output
- Missing namespace? Check that the upstream action is listed in `observe` — the action name is the namespace key

## Project Layout

```
project/
 agent_actions.yml                  # Project config
 agent_workflow/my_workflow/        # Dir name = YAML name = name: field
   agent_config/my_workflow.yml
   agent_io/staging/                # Input data
   agent_io/target/                 # Output per action
   agent_io/store/                  # Durable database
   seed_data/                       # Static reference data
 prompt_store/                      # Prompt templates
 schema/                            # Output schemas (flat — no subdirs)
 tools/my_workflow/                 # UDF tool scripts
```

## Context Scope

Every action declares `context_scope` — this is the core abstraction. It controls exactly what data flows in and out, replacing implicit data passing with explicit declarations.

```yaml
- name: generate_explanation
  dependencies: [extract_facts]
  context_scope:
    observe:                         # What the LLM/tool sees
      - extract_facts.*              # All fields from parent
      - source.page_content          # Original input via lineage
    passthrough:                     # Forwarded to output, LLM never sees it
      - source.url
    drop:                            # Excluded from context entirely
      - extract_facts.debug_info
```

| Directive | LLM sees it? | In output? | Use for |
|-----------|:---:|:---:|---|
| `observe` | Yes | No | Data the action processes |
| `passthrough` | No | Yes | Metadata, IDs, fields downstream needs |
| `drop` | No | No | Noise reduction, bias prevention |

Actions referenced in `observe`/`passthrough` but not in `dependencies` are auto-inferred as context dependencies — no need to list them twice.

## Schema: What Gets Generated

`schema` declares the fields an action **creates from scratch**. Every schema field is generated new by the LLM or returned by the tool.

**A field must never appear in both schema and observe/passthrough.** Schema means "generate this." If you put an upstream field in schema, the LLM regenerates it non-deterministically, causing silent data drift. This is the most common source of data corruption in multi-action pipelines.

**Field placement decision:**
- Action creates this field → `schema`
- Action reads this field → `observe`
- Field must reach downstream unchanged → `passthrough`

## Actions

**LLM action** — sends a prompt to a model, gets structured output:
```yaml
- name: classify_issue
  dependencies: [source]
  model_vendor: openai
  model_name: gpt-4o-mini
  schema: { issue_type: string, severity: string }
  prompt: $support_resolution.Classify_Issue
  context_scope:
    observe: [source.*]
```

**Tool action** — runs a Python function for deterministic logic:
```yaml
- name: aggregate_votes
  dependencies: [score_quality]
  kind: tool
  impl: aggregate_quality_scores
  context_scope:
    observe: [score_quality.*]
```

### Designing Multi-Action Pipelines

Every action falls into one of three roles. Mixing them causes bugs:

1. **Generation** — LLM creates new content. Schema has all output fields. Non-determinism is expected.
2. **Judgment** — LLM evaluates existing content. Schema has ONLY the judgment output (e.g., `decision_reasoning`). All data being judged is `observe` (for reading) and `passthrough` (for forwarding). Never put upstream fields in a judge's schema — the LLM will regenerate them with drift.
3. **Transformation** — Tool processes content deterministically. No LLM, no non-determinism.

```yaml
# Judge action: schema = decision ONLY, data = passthrough
- name: review_quality
  schema:
    decision_reasoning: string         # Only field this action creates
  context_scope:
    observe: [write_content.*]         # Judge reads this
    passthrough:                       # Data survives unchanged
      - write_content.question
      - write_content.answer
```

**Design test:** For every LLM action, ask: "Is this action creating new content, or evaluating existing content?" If evaluating, its schema should contain ONLY the evaluation output.

## Writing UDFs

Observed fields arrive **namespaced by action name** in RECORD mode tools. Each upstream action's fields are nested under its name as a key.

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def enrich_listing(data: dict[str, Any]) -> list[dict[str, Any]]:
    # RECORD mode: fields are namespaced by upstream action
    title = data["extract_listing"]["listing_title"]

    # Seed data is under the "seed" namespace
    rules = data["seed"]["marketplace_rules"]

    return [{"enriched_title": f"{title} — {rules.get('brand', '')}"}]
```

A few things to remember:
- **RECORD mode**: Fields are namespaced — access with `data["action_name"]["field"]`
- **No collisions**: Each action's fields are isolated under its namespace, so field name conflicts cannot occur
- **FILE mode**: Access fields via `record["content"]["action_name"]["field"]`
- Seed data: `data["seed"]["key"]` (requires `observe: [seed.*]`)
- Return `list[dict]` — or `dict` when the YAML uses `passthrough`

## Guards

Guards filter records based on upstream output. The key insight: guards check **input** to the action, not its own output. So you place the guard on the action that *consumes* the data, not the one that *produces* it.

Guard conditions evaluate against **dotted namespace paths** from the action's observed data. If you observe `extract_claims.*`, the guard references fields as `extract_claims.claims`, `extract_claims.confidence`, etc.

```yaml
- name: extract_claims              # Produces claims — no guard here

- name: validate_claims
  dependencies: [extract_claims]
  guard:
    condition: 'len(extract_claims.claims) >= 1 and extract_claims.confidence >= 0.7'
    on_false: "filter"              # filter = remove record | skip = pass through
  context_scope:
    observe: [extract_claims.*]
```

Quote string literals: `status == "approved"` — unquoted strings are treated as field names and produce a preflight error.

## Versions

When you need consensus (multiple independent judgments on the same data), use versions to run an action N times in parallel, then merge:

```yaml
- name: score_quality
  versions: { range: [1, 3], mode: parallel }
  schema: { score: number, reasoning: string }

- name: aggregate_scores
  dependencies: [score_quality]
  kind: tool
  impl: aggregate_quality_scores
  version_consumption: { source: score_quality, pattern: merge }
  context_scope:
    observe: [score_quality.*]
```

**RECORD mode** — each version is a separate namespace:
```python
score_1 = data["score_quality_1"]["score"]  # 8
score_2 = data["score_quality_2"]["score"]  # 7

# Iterate all versions:
scores = [ns["score"] for name, ns in data.items() if name.startswith("score_quality_")]
```

**FILE mode** — version namespaces are nested dicts inside `content`:
```python
# Nested dict access:
scorer_1 = record["content"]["score_quality_1"]
score = scorer_1["score"]

# Or iterate dynamically:
for key, val in record["content"].items():
    if key.startswith("score_quality_") and isinstance(val, dict):
        scores.append(val.get("score", 0))
```

**Voting rule matters:** With 3 voters and majority rule (2/3 must reject), a biased prompt makes each voter 70% likely to reject → overall rejection is ~84%. Switching to unanimous (all 3 must agree) with the same bias → ~34%. Match the voting rule to the prompt's bias direction: if the prompt leans toward rejection, require unanimity to reject.

## Seed Data and Prompts

**Seed data** — static JSON loaded into context. This is the most powerful steering mechanism for small models — they treat seed data as ground truth and won't override it. Put exam alignment, design rules, and domain examples here rather than in prompt text.

```yaml
defaults:
  context_scope:
    seed_path:
      rubric: $file:evaluation_rubric.json
```

In prompts: `{{ seed.rubric.min_score }}`. In UDFs (RECORD mode): `data["seed"]["rubric"]` — seed data is under the `seed` namespace. Requires `observe: [seed.*]` or `observe: [seed.rubric]` in the action config. The config key is `seed_path:` but the prompt prefix is `seed.` — using `seed_data.` is a common mistake that silently resolves to empty.

**Prompt templates** — defined in `prompt_store/workflow_name.md`:
```markdown
{prompt Classify_Issue}
Classify: {{ source.ticket_text }}
Categories: {{ seed.routing_rules.categories }}
{end_prompt}
```
Reference as `prompt: $workflow_name.Classify_Issue`.

**Prompt design for small models** — small models (gpt-4o-mini, gpt-5-mini) follow rules literally. A few principles that prevent common failures:

- **Nuance guides over checklists.** Rigid filter criteria become hard boundaries the model can't negotiate around. Instead of "FILTER if foundational," write "foundational doesn't mean useless — keep if it's a building block."
- **One heuristic over five criteria.** "Ask yourself: if a student gets this wrong, would the explanation teach them something?" works better than a 5-point AND-gate checklist. Small models are good at holistic judgment when framed as one question.
- **Never put target rates in prompts.** "A good pipeline should filter 20-40%" makes the model aim for that range regardless of input quality.
- **Never reference field names.** "Explain why distractor_1_text is wrong" → the model outputs "People might choose distractor_1_text because..." Use natural language: "the wrong option."
- **Use reprompt validation for structural quality.** Prompt instructions are hope; validation code is enforcement. If correct answers must not always be in position A, write a validation UDF that rejects and retries — don't rely on the prompt instruction alone.
- **Keep output schemas minimal.** Small models frequently drop one of two required fields. Collapse to a single field and structure content via prompt instructions when possible.

## Debugging

When output looks wrong, start with: what did the upstream action actually produce?

```bash
cat agent_io/target/<action>/sample.json | python3 -c "
import json, sys; data = json.load(sys.stdin)
print(f'{len(data)} records')
if data:
    rec = data[0]
    content = rec['content']
    print('namespaces:', list(content.keys())[:10])
    for ns, fields in content.items():
        if isinstance(fields, dict):
            print(f'  {ns}: {list(fields.keys())[:5]}')
    print('record keys:', [k for k in rec if k != 'content'][:10])
"
```

Use `record_limit: 2` on any action to test with minimal API spend. Check `events.json` for guard/error events. For the full triage checklist and prompt trace inspection, read **[Debugging Guide](references/debugging-guide.md)**.

## References

Read these when you need depth beyond what's covered above:

### Configuration
- **[YAML Schema](references/yaml-schema.md)** — all action fields, config hierarchy, dependency patterns, vendors
- **[Schema Design Guide](references/schema-design-guide.md)** — inline vs file, required/optional, TypedDict mapping, field name alignment
- **[Context Scope](references/context-scope-guide.md)** — observe/drop/passthrough, output_field, seed data details

### Building
- **[UDF Reference](references/udf-reference.md)** — @udf_tool decorator, record/file mode, namespaced field access, passthrough, version merge
- **[Action Anatomy](references/action-anatomy.md)** — action structure, pre-creation checklist, data lineage, record matching
- **[Prompt Patterns](references/prompt-patterns.md)** — Jinja2 templates, variable access, max_tokens/temperature, anti-patterns
- **[Dynamic Content Injection](references/dynamic-content-injection.md)** — tool action injection pattern for randomized/computed prompt content

### Patterns
- **[Workflow Patterns](references/workflow-patterns.md)** — fan-in, diamond, ensemble, conditional merge, map-reduce
- **[Data Flow Patterns](references/data-flow-patterns.md)** — source format, metadata, data shapes, grounded retrieval
- **[Aggregation Patterns](references/aggregation-patterns.md)** — reduce_key, fan-in matching, merging parallel branches
- **[HITL Patterns](references/hitl-patterns.md)** — human-in-the-loop with guards, lineage, passthrough

### Quality & Debugging
- **[Reprompt Patterns](references/reprompt-patterns.md)** — validation UDFs, retry configuration, schema-based reprompt
- **[Framework Contracts](references/framework-contracts.md)** — 28 contracts: what works, what doesn't, workarounds
- **[Debugging Guide](references/debugging-guide.md)** — triage checklist, caching behavior, prompt traces, error messages
- **[CLI Reference](references/cli-reference.md)** — run, render, validate-udfs, batch mode, debug commands

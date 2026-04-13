---
name: agent-actions-workflow
description: Build, configure, and debug agent-actions agentic workflows. Use this skill whenever the user works with workflow YAML configs, writes UDF tool functions, configures context_scope (observe/passthrough/drop), sets up guards, versions, schemas, seed data, prompt templates, reprompt validation, batch mode, HITL actions, or reduce_key aggregation. Also trigger when debugging pipeline output — empty records, guard filtering issues, schema mismatches, unexpected action results, caching problems, or stale re-runs. Trigger on CLI questions about agac run, agac render, agac validate-udfs, or agac batch. Even if the user just says "add an action", "why is my output empty", "my UDF returns None", or "records are being filtered", this skill applies.
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
    → observe resolves fields via lineage (historical lookup)
      → LLM/tool receives observed fields (namespaced for tools, Jinja-accessible for prompts)
        → Tool processes and returns result
          → passthrough fields merge into output
            → Output stored with extended lineage
              → Next action's observe resolves via this lineage
```

Once you understand this chain, most issues become obvious:
- UDF gets None for a field? Fields are namespaced — use `content["action_name"]["field"]`
- Downstream can't see a field? It wasn't in `passthrough` — only `observe` fields reach the LLM, `passthrough` fields reach the output
- Historical lookup fails? Lineage is broken — check the upstream action's output for correct `lineage` arrays

## Project Layout

```
project/
 agent_actions.yml                  # Project config
 agent_workflow/my_workflow/        # Dir name = YAML name = name: field
   agent_config/my_workflow.yml
   agent_io/staging/                # Input data
   agent_io/target/                 # Output per action
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

## Writing UDFs

Observed fields arrive **namespaced by the action that produced them**. This matters because multiple upstream actions can share field names without collision.

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def enrich_listing(data: dict[str, Any]) -> list[dict[str, Any]]:
    content = data.get("content", data)

    # Upstream fields are under the action name
    copy = content.get("write_marketing_copy", {})
    title = copy.get("listing_title", "")

    # Seed data lives under "seed"
    rules = content.get("seed", {}).get("marketplace_rules", {})

    return [{"enriched_title": f"{title} — {rules.get('brand', '')}"}]
```

A few things to remember:
- Access fields as `content["action_name"]["field"]` — not `content["field"]` (flat access returns None)
- Seed data: `content["seed"]["key"]`
- Version merge: `content["score_quality_1"]`, `content["score_quality_2"]`, etc.
- Return `list[dict]` — or `dict` when the YAML uses `passthrough`
- The `data.get("content", data)` wrapper is a safety net that should always be there

## Guards

Guards filter records based on upstream output. The key insight: guards check **input** to the action, not its own output. So you place the guard on the action that *consumes* the data, not the one that *produces* it.

Guard conditions evaluate against **flattened** field names from the action's observed data. If you observe `extract_claims.*`, the guard sees `claims` and `confidence` directly — not `extract_claims.claims`.

```yaml
- name: extract_claims              # Produces claims — no guard here

- name: validate_claims
  dependencies: [extract_claims]
  guard:
    condition: 'len(claims) >= 1 and confidence >= 0.7'
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

The merge tool receives each version namespaced: `content["score_quality_1"]["score"]`, `content["score_quality_2"]["score"]`, etc.

## Seed Data and Prompts

**Seed data** — static JSON loaded into context:
```yaml
defaults:
  context_scope:
    seed_path:
      rubric: $file:evaluation_rubric.json
```

In prompts: `{{ seed.rubric.min_score }}`. In UDFs: `content.get("seed", {}).get("rubric", {})`. The config key is `seed_path:` but the reference prefix is `seed.` — using `seed_data.` is a common mistake that silently resolves to empty.

**Prompt templates** — defined in `prompt_store/workflow_name.md`:
```markdown
{prompt Classify_Issue}
Classify: {{ source.ticket_text }}
Categories: {{ seed.routing_rules.categories }}
{end_prompt}
```
Reference as `prompt: $workflow_name.Classify_Issue`.

## Debugging

When output looks wrong, start with: what did the upstream action actually produce?

```bash
cat agent_io/target/<action>/sample.json | python3 -c "
import json, sys; data = json.load(sys.stdin)
print(f'{len(data)} records')
if data: print(list(data[0].get('content', data[0]).keys())[:10])
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
- **[UDF Reference](references/udf-reference.md)** — @udf_tool decorator, record/file mode, namespaced access, passthrough, version merge
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

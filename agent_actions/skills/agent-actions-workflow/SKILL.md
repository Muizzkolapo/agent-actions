---
name: agent-actions-workflow
description: Build, configure, and debug agent-actions agentic workflows. Use this skill whenever the user works with workflow YAML configs, writes UDF tool functions, configures context_scope (observe/passthrough/drop), sets up guards, versions, schemas, seed data, prompt templates, reprompt validation, batch mode, HITL actions, reduce_key aggregation, or cross-workflow chaining. Also trigger when debugging pipeline output — empty records, guard filtering, schema mismatches, unexpected action results, caching problems, or stale re-runs. Trigger on CLI questions about agac run, agac render, agac validate-udfs, or agac batch. Even if the user just says "add an action", "why is my output empty", "my UDF returns None", "records are being filtered", "chain workflows", or "run downstream", this skill applies.
---

# Agent Actions Workflow Builder

agent-actions is declarative. You describe WHAT each action does and WHAT data it needs. The framework handles execution order, data routing, and record provenance — like Terraform handles state.

Before changing anything, read the workflow YAML and check what upstream actually produces. Most issues come from mismatched expectations between actions.

```bash
agac run -a my_workflow              # Run workflow
agac render -a my_workflow           # Compiled YAML (schemas inlined, versions expanded)
```

## Data Flow

```
Source record → framework adds source_guid, node_id, lineage
  → observe resolves fields via lineage
    → LLM/tool receives observed fields
      → passthrough merges into output (tool never saw them)
        → output stored with extended lineage → next action resolves via this lineage
```

## Context Scope

The core abstraction. Every action declares what data flows in and out.

| Directive | What it does | LLM/tool sees it? | In output? |
|-----------|-------------|:---:|:---:|
| `observe` | **Loads** data from upstream via lineage | Yes | No |
| `passthrough` | **Forwards** data to output, bypassing the action | No | Yes |
| `drop` | **Excludes** data from context | No | No |

Actions referenced in `observe`/`passthrough` but not in `dependencies` are **auto-inferred** as context dependencies — no need to list them in `dependencies`.

The reason this matters: `observe` controls what gets loaded into the action's resolved context. Downstream actions consuming this action's output through version merge or lineage can only access fields that were loaded here. If a downstream aggregator needs `upstream.field`, the intermediate action must observe it.

## Schema: What Gets Generated

`schema` declares fields the action **creates from scratch**. Every field in schema is generated new — the LLM fills it in, the tool returns it.

**A field must never appear in both schema and observe/passthrough.** Schema means "generate this." If you put an upstream field in schema, the LLM regenerates it non-deterministically, causing silent data drift. This is the most common source of data corruption in multi-action pipelines.

```yaml
# Judge action: schema = judgment only, reviewed data = passthrough
schema:
  decision_reasoning: string         # the only field this action creates
context_scope:
  passthrough:                       # data survives unchanged
    - write_question.question
    - write_question.answer
  observe:                           # judge reads these to decide
    - write_question.answer_explanation
```

**Field placement decision:**
- Action creates this field → `schema`
- Action reads this field → `observe`
- Field must reach downstream unchanged → `passthrough`

## Writing UDFs

Observed fields arrive **namespaced**: `content["action_name"]["field"]`. Flatten them, then build output with **only schema-declared fields**:

```python
@udf_tool()
def my_tool(data: dict[str, Any]) -> list[dict[str, Any]]:
    content = data.get("content", data)

    # Flatten namespaced fields
    flat = {}
    for key, value in content.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value

    # Return ONLY schema fields — never flat.copy() or data.copy()
    result = {
        "computed_field": process(flat.get("input_field", "")),
        "question": flat.get("question", ""),
    }
    for field in ("source_quote", "answer_explanation"):
        if field in flat:
            result[field] = flat[field]

    return [result]
```

Copying all input into output (`flat.copy()`) leaks upstream fields — including arbitrary text that happens to be a dict key — past schema validation. The framework validates output against the schema and rejects unexpected fields.

**FILE mode:** Each record carries a `node_id` the framework uses to track lineage. Return the original record dict to preserve it. Return a new dict without `node_id` for aggregation (creates fresh lineage). Read business data from `record["content"]["field"]`.

```python
# Passthrough: return record → lineage preserved
outputs.append(record)
# Transform: mutate content, return record → lineage preserved
record["content"]["score"] = normalized
outputs.append(record)
# Aggregation: new dict → fresh lineage
outputs.append({"summary": "merged", "count": len(data)})
```

## Versions and Aggregation

Run an action N times in parallel, then merge. The aggregator receives each version namespaced: `content["score_quality_1"]["score"]`, etc.

The aggregator can only access fields from indirect upstreams if the **version source loaded them** via observe. If the aggregator needs `upstream.answer`, add it to the version source's observe — otherwise the merge can't resolve it.

```yaml
- name: validator
  versions: { range: [1, 3], mode: parallel }
  context_scope:
    observe:
      - content_action.*
      - upstream.answer              # aggregator needs this — load it here

- name: aggregate
  version_consumption: { source: validator, pattern: merge }
  context_scope:
    observe:
      - validator.*
      - upstream.answer              # resolves because version source loaded it
```

## Modifying Actions

When changing an existing action:

- **Remove a field from schema** → check every downstream observe/passthrough reference to it. They break.
- **Move schema → passthrough** → field is no longer generated, it's forwarded. Verify upstream produces it.
- **Move observe → passthrough** → tool/LLM can no longer read it, but it still appears in output.
- **After any change** → clear cached data (target_data + prompt_trace + run_results.json) and rerun. The framework caches aggressively — stale data masks your changes.

## Creating Actions

| Type | YAML needs | Python | Prompt | Schema |
|------|-----------|:---:|:---:|:---:|
| LLM | `schema` + `prompt` + `context_scope` | — | Yes | Inline or file |
| Tool (Record) | `kind: tool` + `impl` | `@udf_tool()` | — | File |
| Tool (FILE) | `kind: tool` + `granularity: file` | `@udf_tool(granularity=FILE)` | — | File |
| Versioned | `versions` + `version_consumption` | Aggregator UDF | Voter prompt | Both |
| Judge | schema = decision only | — | Yes | Inline |
| HITL | `kind: hitl` + `granularity: file` | — | — | — |

Templates in `assets/templates/`. Checklist: **[Action Anatomy](references/action-anatomy.md)**.

## Debugging

Start with: what did upstream actually produce? Query the DB — see **[Debugging Guide](references/debugging-guide.md)** for the full triage checklist, inspection scripts, and cache clearing. Field consistency issues (one record missing a field breaks all downstream) are covered in **[Framework Contracts](references/framework-contracts.md)** §30.

`record_limit: 2` on any action to test with minimal API spend.

## References

**Configuration:** [YAML Schema](references/yaml-schema.md) · [Schema Design](references/schema-design-guide.md) · [Context Scope](references/context-scope-guide.md)

**Building:** [UDF Reference](references/udf-reference.md) · [Action Anatomy](references/action-anatomy.md) · [Prompt Patterns](references/prompt-patterns.md) · [Dynamic Injection](references/dynamic-content-injection.md)

**Patterns:** [Workflow](references/workflow-patterns.md) · [Data Flow](references/data-flow-patterns.md) · [Aggregation](references/aggregation-patterns.md) · [HITL](references/hitl-patterns.md)

**Quality:** [Reprompt](references/reprompt-patterns.md) · [Framework Contracts](references/framework-contracts.md) (33 contracts) · [Debugging](references/debugging-guide.md) · [CLI](references/cli-reference.md)

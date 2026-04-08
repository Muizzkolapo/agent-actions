---
name: agent-actions-workflow
description: Build and debug agent-actions agentic workflows. Use when creating workflows, writing UDFs, configuring context_scope, guards, versioned actions, or debugging pipeline outputs. Trigger for any question about agent_actions.yml, workflow YAML, UDF tools, context_scope observe/passthrough/drop, guards, schemas, or prompt templates.
---

# Agent Actions Workflow Builder

Build workflows with YAML configs, UDF tools, and context scoping.

## Before You Touch Code

1. Read the workflow YAML — understand the full pipeline
2. Check parent outputs — `cat agent_io/target/<parent>/sample.json`
3. Check what downstream actions `observe` — will your output satisfy them?
4. Ask clarifying questions — don't assume goals, thresholds, or edge cases

## Quick Reference

```bash
agac run -a my_workflow              # Run workflow
agac render -a my_workflow           # See compiled YAML (schemas inlined, versions expanded)
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow  # Debug output
```

## Project Structure

```
project/
 agent_actions.yml                  # Project config
 agent_workflow/
   my_workflow/                     # Directory name = YAML filename = name: field
     agent_config/my_workflow.yml
     agent_io/
       staging/                     # Input data
       target/                      # Output per action
     seed_data/                     # Reference data (optional)
 prompt_store/                      # Prompt templates
 schema/                            # Output schemas (root only, no subdirs)
 tools/my_workflow/                  # UDF tool scripts
```

## Context Scope (Required)

Every action must declare `context_scope`. It controls what data the action sees.

| Directive | Purpose | LLM sees it? | In output? |
|-----------|---------|:---:|:---:|
| `observe` | Fields the LLM/tool processes | Yes | No |
| `passthrough` | Fields forwarded to output untouched | No | Yes |
| `drop` | Fields excluded from context | No | No |

```yaml
- name: generate_explanation
  dependencies: [extract_facts]
  context_scope:
    observe:
      - extract_facts.*              # All fields from parent
      - source.page_content          # Original input via lineage
    passthrough:
      - source.url                   # Forward to output without LLM seeing it
    drop:
      - extract_facts.debug_info     # Exclude noise
```

Actions in `observe`/`passthrough` but not in `dependencies` are auto-inferred as context dependencies.

## Action Types

**LLM Action:**
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

**Tool Action (UDF):**
```yaml
- name: aggregate_votes
  dependencies: [score_quality]
  kind: tool
  impl: aggregate_quality_scores
  context_scope:
    observe: [score_quality.*]
```

## UDF Pattern

Observed fields arrive **namespaced by action name**:

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def my_function(data: dict[str, Any]) -> list[dict[str, Any]]:
    content = data.get("content", data)

    # Access upstream fields by action namespace
    upstream = content.get("extract_facts", {})
    facts = upstream.get("candidate_facts_list", [])

    # Seed data under "seed" namespace
    rules = content.get("seed", {}).get("evaluation_rubric", {})

    return [{"fact_count": len(facts), "threshold": rules.get("min_facts", 3)}]
```

**Key rules:**
- Fields arrive as `content["action_name"]["field"]`, not `content["field"]`
- Seed data: `content["seed"]["key"]`
- Version merge data: `content["action_1"]["field"]`, `content["action_2"]["field"]`
- Return `list[dict]` (or `dict` when using passthrough)
- Always handle content wrapper: `data.get("content", data)`

## Guards

Guards filter records based on **input** data. Place on the consuming action:

```yaml
- name: extract_claims          # Produces claims — no guard here
  schema: { claims: array, confidence: number }

- name: validate_claims
  dependencies: [extract_claims]
  guard:
    condition: 'len(claims) >= 1 and confidence >= 0.7'
    on_false: "filter"          # filter (remove) | skip (pass through)
  context_scope:
    observe: [extract_claims.*]
```

String literals must be quoted: `status == "approved"`, not `status == approved`.

## Versions (Parallel Consensus)

Run the same action N times in parallel, then merge results:

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
    observe: [score_quality.*]    # Wildcard captures all versions
```

The tool receives each version namespaced: `content["score_quality_1"]`, `content["score_quality_2"]`, etc.

## Seed Data

Static reference data loaded from JSON files:

```yaml
defaults:
  context_scope:
    seed_path:
      rubric: $file:evaluation_rubric.json
      rules: $file:marketplace_rules.json
```

Access in prompts as `{{ seed.rubric.min_score }}`. In UDFs as `content.get("seed", {}).get("rubric", {})`.

Config key is `seed_path:` / `seed_data:`, but reference prefix is always `seed.` — not `seed_data.`.

## Prompt Templates

Define in `prompt_store/workflow_name.md`:

```markdown
{prompt Classify_Issue}
Classify this support ticket:
{{ source.ticket_text }}

Categories: {{ seed.routing_rules.categories }}
{end_prompt}
```

Reference: `prompt: $workflow_name.Classify_Issue`

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Guard on wrong action | Place on consuming action (guards check INPUT) |
| UDF returns dict not list | Return `[result]` (dict only with passthrough) |
| Flat field access in UDF | Use `content.get("action_name", {}).get("field")` |
| Dependency not in context_scope | Add `action.*` to observe |
| `seed_data.` in templates | Use `seed.` prefix, not `seed_data.` |
| Schema in subdirectory | Must be in root `schema/` dir |
| Unquoted guard string | Use `status == "approved"`, not `status == approved` |

## Debugging

When investigating `agac run` output: read **[Debugging Guide](references/debugging-guide.md)** for the full triage checklist, prompt trace inspection, and known edge cases.

Quick checks:
- Compare tally line against actual record counts in `target/`
- Check `events.json` for guard/error events
- Use `record_limit: 2` on any action to test with minimal API spend

## Reference Files

| Doc | When to read |
|-----|-------------|
| [YAML Schema](references/yaml-schema.md) | Full config reference, all action fields |
| [UDF Patterns](references/udf-patterns.md) | Data access, passthrough, version merge, FILE granularity |
| [Context Scope](references/context-scope-guide.md) | observe/drop/passthrough details, seed data |
| [Debugging Guide](references/debugging-guide.md) | Triage checklist, prompt traces, error messages |
| [Common Pitfalls](references/common-pitfalls.md) | 28 documented pitfalls with fixes |
| [Workflow Patterns](references/workflow-patterns.md) | Fan-in, diamond, ensemble, conditional patterns |
| [Action Anatomy](references/action-anatomy.md) | Action structure, data lineage, record matching |
| [Prompt Patterns](references/prompt-patterns.md) | Prompt store syntax, Jinja2 templates |
| [CLI Reference](references/cli-reference.md) | agac commands and flags |

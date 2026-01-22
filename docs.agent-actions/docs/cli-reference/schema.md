---
title: schema Command
description: Analyze agentic workflow schemas and field dependencies
sidebar_position: 6
---

# schema Command

Before running an agentic workflow, you often want to understand its structure: What data does each action expect? What fields does it produce? Are there any mismatched references?

The `schema` command answers these questions through static analysis—examining your configuration without making any API calls. Think of it like a compiler checking your code before execution.

## Project Detection

The schema command:
- Works from any subdirectory within your project
- Automatically detects project root by finding `agent_actions.yml`
- Shows project root detection: `📁 Project root: <path>`

## Usage

**What data flows through my agentic workflow?** The schema command answers this by showing what fields each action expects and produces.

```bash
agac schema -a <agentic-workflow-name> [options]
```

Consider what happens when you reference a field that doesn't exist - maybe you typed `extract_facts.fact` instead of `extract_facts.facts`. Without schema validation, you'd discover this error at runtime, potentially after processing hundreds of records. The schema command catches these mismatches upfront.

This works similar to TypeScript's type checking: Agent Actions analyzes your configuration statically to validate data flow before any execution begins.

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agentic workflow name (required) |
| `-u, --user-code DIRECTORY` | Path to user code directory containing UDFs |
| `--json` | Output as JSON for programmatic use |
| `-v, --verbose` | Show detailed data flow visualization |

**Examples:**

```bash
# Show schemas in table format
agac schema -a my_workflow

# Output as JSON for programmatic use
agac schema -a my_workflow --json

# Show detailed data flow tree
agac schema -a my_workflow --verbose

# Include UDF schemas from user code
agac schema -a my_workflow -u ./tools
```

Let's walk through what the output tells you:

**Table Output Example:**

```
                    Action Schemas: my_workflow
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Action           ┃ Type   ┃ Input             ┃ Output           ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ fact_extractor   │ llm    │ required:         │ fact, quote,     │
│                  │        │ source.syllabus,  │ technical_level  │
│                  │        │ source.url        │                  │
├──────────────────┼────────┼───────────────────┼──────────────────┤
│ validate_facts   │ tool   │ required: fact,   │ is_valid,        │
│                  │        │ quote             │ confidence       │
└──────────────────┴────────┴───────────────────┴──────────────────┘
```

**Schema Sources:**

| Action Type | Input Schema Source | Output Schema Source |
|-------------|---------------------|----------------------|
| LLM | Template references (`{{ action.field }}`) and context_scope | `schema` field |
| Tool | `input_type` TypedDict from `@udf_tool` decorator | `output_type` TypedDict from `@udf_tool` decorator |

**What It Shows:**

- **Input**: Fields the action requires from upstream actions or source data
- **Output**: Fields the action produces for downstream actions
- **(none)**: No input fields required
- **(schemaless)**: Output schema not defined (tool without `output_type`)
- **(dynamic)**: Schema determined at runtime

:::tip Use for Debugging
Run `schema` to quickly understand data flow and catch field reference errors before executing your agentic workflow.
:::

:::info Limitation
Schema analysis works best when your actions have explicit schemas defined. For tools without `output_type` annotations, you'll see "(schemaless)"—the command can't infer what fields they produce.
:::

## See Also

- [Troubleshooting](./troubleshooting) - Debug agentic workflow issues
- [run Command](./run) - Execute agentic workflows with `--validate-only`

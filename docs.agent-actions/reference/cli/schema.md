---
title: schema Command
description: Analyze agentic workflow schemas and field dependencies
sidebar_position: 6
---

# schema Command

The `schema` command analyzes your workflow configuration to show what fields each action expects and produces - without making any API calls.

```bash
agac schema -a <workflow-name> [options]
```

This catches field reference errors upfront. For example, if you typed `extract_facts.fact` instead of `extract_facts.facts`, you'd discover this at runtime after processing hundreds of records. The schema command validates these references statically.

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

## Options

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Workflow name (required) |
| `-u, --user-code DIRECTORY` | Path to user code directory containing tools |
| `--json` | Output as JSON for programmatic use |
| `-v, --verbose` | Show detailed data flow visualization |

## Examples

```bash
# Show schemas in table format
agac schema -a my_workflow

# Output as JSON for programmatic use
agac schema -a my_workflow --json

# Show detailed data flow tree
agac schema -a my_workflow --verbose

# Include tool schemas from user code
agac schema -a my_workflow -u ./tools
```

## Output Reference

The output shows:

- **Input**: Fields the action requires from upstream actions or source data
- **Output**: Fields the action produces for downstream actions
- **(none)**: No input fields required
- **(schemaless)**: Output schema not defined (tool without a YAML `schema:` field)
- **(dynamic)**: Schema determined at runtime

**Schema Sources by Action Type:**

| Action Type | Input Schema Source | Output Schema Source |
|-------------|---------------------|----------------------|
| LLM | Template references and context_scope | `schema` field |
| Tool | `context_scope` in workflow YAML | `schema` field in workflow YAML |

## See Also

- [run Command](./run) - Execute agentic workflows
- [Troubleshooting](./troubleshooting) - Debug workflow issues

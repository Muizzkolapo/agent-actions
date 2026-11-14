---
title: schema Command
description: Analyze the schemas and the field dependencies of a workflow
sidebar_position: 6
---

# schema Command

The `schema` command analyzes your workflow configuration. It shows the fields that each action expects and the fields that each action produces. It does not make API calls.

```bash
agac schema -a <workflow-name> [options]
```

This command finds field reference errors before a run. For example, if you typed `extract_facts.fact` in place of `extract_facts.facts`, you would find the error at runtime. You would find it after the workflow processed hundreds of records. The schema command validates these references statically.

:::note[Run from Anywhere]
You can run this command from any subdirectory in your project.
:::

## Options

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | The workflow name (required) |
| `-u, --user-code DIRECTORY` | The path to the user code directory that contains the tools |
| `--json` | Write the output as JSON, for use by programs |
| `-v, --verbose` | Show a detailed diagram of the data flow |

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

- **Input**: The fields that the action requires from upstream actions or from the source data
- **Output**: The fields that the action produces for downstream actions
- **(none)**: The action requires no input fields, or produces no output fields
- **(schemaless)**: The output schema is not defined (a tool without a YAML `schema:` field)
- **(dynamic)**: The schema is set at runtime
- **(template-based)**: The input fields come from the prompt template

**Schema Sources for Each Action Type:**

| Action Type | Input Schema Source | Output Schema Source |
|-------------|---------------------|----------------------|
| LLM | Template references and context_scope | `schema` field |
| Tool | `context_scope` in workflow YAML | `schema` field in workflow YAML |

## See Also

- [run Command](./run): Run workflows
- [Troubleshooting](./troubleshooting): Debug workflow problems

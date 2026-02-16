---
title: Tool Commands
description: Commands for managing custom tools
sidebar_position: 5
---

# Tool Commands

Custom tools let you extend Agent Actions with deterministic logic. They handle tasks that LLMs can't do alone, like calling APIs, validating data, or transforming outputs.

Commands for discovering and validating tools:

## list-udfs

**What tools are available in my project?** This command scans your code directory for Python functions decorated with `@udf_tool`.

```bash
agac list-udfs -u <user-code-path> [options]
```

Discovers all tools and displays their metadata - location, file path, and documentation.

**Options:**
| Option | Description |
|--------|-------------|
| `-u, --user-code` | Path to user code directory containing tools (required) |
| `--json` | Output as JSON for programmatic use |
| `--verbose` | Show full signatures and docstrings |

**Examples:**

```bash
# List tools in table format
agac list-udfs -u user_code/

# Output as JSON
agac list-udfs -u user_code/ --json

# Show full details (signatures, docstrings)
agac list-udfs -u user_code/ --verbose
```

:::tip
Use this command to verify which tools were discovered from your code directory before running your agentic workflow.
:::

## validate-udfs

**Will my agentic workflow find all the tools it needs?** Validates that every `impl` reference in your configuration points to a real, properly decorated function.

```bash
agac validate-udfs -a <agentic-workflow> -u <user-code-path> [options]
```

Catches misspelled function names or missing `@udf_tool` decorators before execution begins.

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent` | Agentic workflow name (required) |
| `-u, --user-code` | Path to user code directory containing tools (required) |

**What it validates:**
- All `impl` references exist in the tool registry
- No duplicate function names across files
- All Python files can be imported without errors
- Functions are properly decorated with `@udf_tool`

**Examples:**

```bash
# Validate agentic workflow config references
agac validate-udfs -a my_workflow -u user_code/
```

:::tip When to Use
Run this command before deploying agentic workflows to catch tool reference errors early. Ideal for CI/CD pipelines where you want to fail fast on configuration errors.
:::

:::info Limitation
Validates that tool references exist and are properly decorated, but doesn't execute the functions. Runtime errors inside your tool code (like API failures or type mismatches) will only surface during actual execution.
:::

## See Also

- [Tool Actions Reference](../tools/) - Complete tool documentation
- [Custom Tools](../../guides/custom-tools) - Getting started with tools

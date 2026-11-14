---
title: Tool Commands
description: Commands that find and validate custom tools
sidebar_position: 5
---

# Tool Commands

Custom tools add deterministic logic to Agent Actions. They do tasks that LLMs cannot do alone, for example API calls, data validation or output transformation.

The commands below find and validate tools:

## list-udfs

This command shows the tools that are available in your project. It scans your code directory for Python functions that have the `@udf_tool` decorator.

```bash
agac list-udfs -u <user-code-path> [options]
```

The command finds all tools and shows their metadata: the location, the file path and the documentation.

**Options:**
| Option | Description |
|--------|-------------|
| `-u, --user-code` | The path to the user code directory that contains the tools (required) |
| `--json` | Write the output as JSON, for use by programs |
| `--verbose` | Show the full signatures and docstrings |

**Examples:**

```bash
# List tools in table format
agac list-udfs -u user_code/

# Output as JSON
agac list-udfs -u user_code/ --json

# Show full details (signatures, docstrings)
agac list-udfs -u user_code/ --verbose
```

Before you run your workflow, use this command to verify which tools it found in your code directory.

## validate-udfs

This command shows if your workflow will find all the tools that it needs. It validates that each `impl` reference in your configuration points to a real function that has the correct decorator.

```bash
agac validate-udfs -a <agentic-workflow> -u <user-code-path> [options]
```

It finds misspelled function names or missing `@udf_tool` decorators before execution starts.

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent` | The workflow name (required) |
| `-u, --user-code` | The path to the user code directory that contains the tools (required) |

**Validated items:**
- All `impl` references exist in the tool registry.
- No two files have the same function name.
- All Python files can be imported without errors.
- The functions have the correct `@udf_tool` decorator.
- Tool references in guards (UDF guards) resolve to registered functions.
- The workflow configuration passes the same structural checks that `inspect`, `schema` and `run` apply.

On failure, the command exits with code 1. It also prints warnings. Examples are a FILE tool whose return type breaks the FILE contract, and a tool that reads an unknown namespace key.

**Examples:**

```bash
# Validate agentic workflow config references
agac validate-udfs -a my_workflow -u user_code/
```

Run this command before you deploy workflows, to find tool reference errors early. It is ideal for CI/CD pipelines in which you want a fast failure on configuration errors.

:::note[Limitation]
The command validates that tool references exist and have the correct decorator. It does not execute the functions. Runtime errors in your tool code (for example API failures or type mismatches) will show only during actual execution.
:::

## See Also

- [Tool Actions Reference](../tools/): The complete documentation for tools
- [Custom Tools](../../guides/custom-tools): Start to use tools

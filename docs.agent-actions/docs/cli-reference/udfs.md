---
title: UDF Commands
description: Commands for managing User-Defined Functions
sidebar_position: 5
---

# UDF Commands

User-Defined Functions (UDFs) let you extend Agent Actions with custom Python logic. Think of UDFs as custom tools you build for your agentic workflow - they handle tasks that LLMs can't do alone, like calling APIs, validating data, or transforming outputs.

Let's explore the commands for discovering and validating UDFs.

## list-udfs

**What UDFs are available in my project?** This command answers that question by scanning your code directory for Python functions decorated with `@udf_tool`.

```bash
agac list-udfs -u <user-code-path> [options]
```

The command discovers all UDFs and displays their metadata - location, file path, and documentation. This is useful when you're building an agentic workflow and want to see which custom functions you can reference.

**Options:**
| Option | Description |
|--------|-------------|
| `-u`, `--user-code` | Path to user code directory containing UDFs (required) |
| `--json` | Output as JSON for programmatic use |
| `--verbose` | Show full signatures and docstrings |
| `--debug` | Enable debug mode |
| `-v` | Enable verbose output |

**Examples:**

```bash
# List UDFs in table format
agac list-udfs -u user_code/

# Output as JSON
agac list-udfs -u user_code/ --json

# Show full details (signatures, docstrings)
agac list-udfs -u user_code/ --verbose
```

**Table Output Example:**

```
Available User-Defined Functions

Function              Location          File
validate_email        validators        user_code/validators.py
                                        Validate email address format
transform_data        transformers      user_code/transformers.py
                                        Transform JSON to dict

Total: 2 function(s)
```

**JSON Output Example:**

```json
[
  {
    "name": "validate_email",
    "module": "validators",
    "file": "/path/to/user_code/validators.py",
    "signature": "(data, **kwargs)",
    "docstring": "Validate email address format."
  }
]
```

:::tip
Use this command to verify which UDFs were discovered from your code directory before running your agentic workflow.
:::

## validate-udfs

**Will my agentic workflow find all the UDFs it needs?** This command validates that every `impl` reference in your configuration points to a real, properly decorated function.

```bash
agac validate-udfs -a <agentic-workflow> -u <user-code-path> [options]
```

Consider what happens when you misspell a function name or forget the `@udf_tool` decorator. Without validation, you'd discover the error mid-execution - after some API calls have already been made. This command catches those errors early, before any execution begins.

**Options:**
| Option | Description |
|--------|-------------|
| `-a`, `--agent` | Agentic workflow name (required) |
| `-u`, `--user-code` | Path to user code directory containing UDFs (required) |
| `--debug` | Enable debug mode |
| `-v`, `--verbose` | Enable verbose output |

**What it validates:**
- All `impl` references exist in the UDF registry
- No duplicate function names across files
- All Python files can be imported without errors
- Functions are properly decorated with `@udf_tool`

**Examples:**

```bash
# Validate agentic workflow config references
agac validate-udfs -a my_workflow -u user_code/
```

**Success Output:**

```
🔍 Discovering UDFs...
✅ Discovered 5 UDF(s)

Loading configuration...
Validating UDF references in config...

✅ All UDF references valid
✅ No duplicate function names

Summary:
  - 3 UDF(s) referenced in config
  - 5 UDF(s) discovered and registered
  - All functions found

Referenced UDFs:
  • validate_email (/path/to/user_code/validators.py)
  • transform_data (/path/to/user_code/transformers.py)
  • enrich_product (/path/to/user_code/enrichers.py)
```

**Error Output (Missing Function):**

```
❌ Function 'validate_emai' not found

This function is not registered. Did you forget the @udf_tool decorator?

Available functions (5):
  • validate_email (/path/to/user_code/validators.py)
  • validate_phone (/path/to/user_code/validators.py)
  ...

Fix:
  1. Check the function name spelling
  2. Ensure the function has @udf_tool decorator
  3. Verify the file is in the user code directory
```

**Error Output (Duplicate Names):**

```
❌ Error: Duplicate function name 'process_data'

First definition:
  Location: validators.process_data
  File: /path/to/user_code/validators.py

Duplicate definition:
  Location: transformers.process_data
  File: /path/to/user_code/transformers.py

Fix:
  Function names must be unique. Rename one of these functions.
```

:::tip When to Use
Run this command before deploying agentic workflows to catch UDF reference errors early. It's ideal for CI/CD pipelines where you want to fail fast on configuration errors.
:::

:::info Limitation
This command validates that UDF references exist and are properly decorated, but it doesn't execute the functions. Runtime errors inside your UDF code (like API failures or type mismatches) will only surface during actual execution.
:::

## See Also

- [UDF Decorator Reference](../reference/tools/udf-decorator) - Complete UDF guide
- [Custom Functions Guide](../getting-started/custom-functions) - Getting started with UDFs

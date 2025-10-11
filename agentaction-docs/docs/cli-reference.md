---
title: CLI Reference
description: Complete reference for Agent Actions command-line interface
sidebar_position: 4
---

# CLI Reference

The Agent Actions CLI provides commands for running workflows, managing agents, and debugging your pipelines.

## Global Flags

These flags work with all commands:

### `--debug`

Enable debug mode with detailed logging and exception traces.

```bash
agent-actions run my-workflow.yaml --debug
```

**Debug mode shows:**
- Structured exception chains with full context
- Complete Python tracebacks for errors
- Detailed logging from all processors
- File paths, operation names, and timestamps

**Use when:**
- Investigating errors or unexpected behavior
- Developing new workflows
- Troubleshooting configuration issues

**Example output:**
```
--- Debug Information ---

Exception Chain:
Level 1: ConfigurationError - Invalid model specified
  Context: {'agent': 'my-agent', 'field': 'model', 'file_path': 'agents/my-agent.yaml'}

Level 2: ValueError - Model 'gpt-5' not found in provider catalog

Full Traceback:
Traceback (most recent call last):
  ...
```

### `--verbose` / `-v`

Enable verbose output with informational messages.

```bash
agent-actions run my-workflow.yaml --verbose
# or
agent-actions run my-workflow.yaml -v
```

**Verbose mode shows:**
- Progress updates for each step
- Configuration loading messages
- Agent execution status
- File operations and validations

**Use when:**
- Monitoring workflow progress
- Verifying configuration is loaded correctly
- Understanding execution flow

### `--version` / `-V`

Display the Agent Actions version.

```bash
agent-actions --version
```

### `-h` / `--help`

Show help message and available commands.

```bash
agent-actions --help
agent-actions run --help
```

## Working Directory

Agent Actions CLI commands automatically detect your project root by searching for `agent_actions.yml`, similar to how git, dbt, and npm work. This means you can run commands from **any subdirectory** within your project.

### How It Works

The CLI walks up the directory tree from your current location looking for `agent_actions.yml`:

```bash
my-project/
├── agent_actions.yml       # Project root marker
├── src/
│   ├── agents/
│   └── utils/
└── tests/

# All of these work the same:

# From project root
cd my-project
agent-actions run my-workflow.yaml
# 📁 Project root: .

# From subdirectory
cd my-project/src/utils
agent-actions run my-workflow.yaml
# 📁 Project root: ../..

# From any depth
cd my-project/src/agents/helpers
agent-actions run my-workflow.yaml
# 📁 Project root: ../../../
```

### Not in a Project?

If you're outside a project directory, you'll get a helpful error:

```bash
$ cd /tmp
$ agent-actions run my-workflow.yaml

Error: Not in an agent-actions project

Could not find 'agent_actions.yml' in current directory or any parent directory.

Current directory: /tmp

Solutions:
  1. Navigate to your agent-actions project directory
  2. Run 'agent-actions init' to create a new project
```

### Commands That Work Anywhere

These commands don't require being in a project:
- `init` - Create a new project
- `--version` - Show version
- `--help` - Display help

## Commands

### `run`

Execute an agent workflow.

```bash
agent-actions run -a <agent-name> [options]
```

**Examples:**
```bash
# Run an agent workflow
agent-actions run -a my_agent

# Run with custom user code
agent-actions run -a my_agent -u ./user_code --use-tools

# Force parallel execution
agent-actions run -a my_agent --parallel
```

**Options:**
- `-a, --agent TEXT` - Agent configuration file name (required)
- `-u, --user_code DIRECTORY` - Path to the user's code folder containing UDFs
- `--use-tools` - Enable tool usage for agents
- `--force` - Force execution even if validation warnings occur
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output
- `--parallel` - Force parallel execution (overrides auto-detection)
- `--no-parallel` - Force sequential execution (overrides auto-detection)
- `--concurrency-limit` - Maximum concurrent agents in parallel execution (default: 5, range: 1-50)

:::tip Run from Anywhere
You can run this command from any subdirectory within your project. The CLI will automatically find your project root.
:::

**Parallel Execution:**

Agent Actions automatically detects when agents can run in parallel based on their dependencies. Agents at the same dependency level execute concurrently, improving workflow performance.

```bash
# Auto-detect parallel execution (default)
agent-actions run my-workflow.yaml

# Force parallel execution
agent-actions run my-workflow.yaml --parallel

# Force sequential execution
agent-actions run my-workflow.yaml --no-parallel

# Limit concurrent agents to 10
agent-actions run my-workflow.yaml --parallel --concurrency-limit 10
```

**Examples:**

```bash
# Basic run
agent-actions run my-workflow.yaml

# Run with verbose output
agent-actions run my-workflow.yaml --verbose

# Run with debug mode for troubleshooting
agent-actions run my-workflow.yaml --debug

# Run with parallel execution and custom concurrency limit
agent-actions run my-workflow.yaml --parallel --concurrency-limit 10
```

**UDF Discovery:**

When your workflow uses User-Defined Functions (UDFs) with the `@udf_tool` decorator, Agent Actions automatically discovers and registers them at workflow start:

```bash
$ agent-actions run my-workflow.yaml -u user_code/

🔍 Discovering UDFs...
✅ Discovered 5 UDF(s)

Running workflow: my-workflow
...
```

See the [UDF Decorator Guide](/guides/udf-decorator) for more information on creating and using UDFs.

### `batch`

Process multiple files in batch mode.

```bash
agent-actions batch <workflow-file> [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

### `test`

Run workflow tests and validations.

```bash
agent-actions test [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

### `clean`

Clean up generated files and caches.

```bash
agent-actions clean [options]
```

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

### `docs`

Generate documentation for your workflows.

```bash
agent-actions docs [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

### `render`

Render Jinja2 templates in agent configuration files without executing them.

This command is useful for:
- **Debugging template issues** - See rendered output before execution
- **Verifying macro expansion** - Check if macros expand correctly
- **Troubleshooting YAML parsing errors** - Identify template-induced YAML issues
- **Learning how templates work** - Understand template expansion

```bash
agent-actions render -a <agent-name> [options]
```

**Examples:**
```bash
# Render agent config to console
agent-actions render -a my_agent

# Render with custom templates directory
agent-actions render -a my_agent -t custom_templates
```

**Options:**

- `-a, --agent TEXT` - Name of the agent to render template for (required)
- `-t, --template-dir TEXT` - Directory containing templates (default: `./templates`)
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

The rendered output is always displayed to the console for quick debugging and verification.

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

### `init`

Initialize a new Agent Actions project.

```bash
agent-actions init [project-name] [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

### `status`

Check workflow execution status.

```bash
agent-actions status [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

### `list-udfs`

List all discovered User-Defined Functions (UDFs).

```bash
agent-actions list-udfs -u <user-code-path> [options]
```

**Arguments:**
- `-u`, `--user-code` - Path to user code directory containing UDFs (required)

**Options:**
- `--json` - Output as JSON for programmatic use
- `--verbose` - Show full signatures and docstrings
- `--debug` - Enable debug mode
- `-v` - Enable verbose output

**Description:**

Scans the user code directory for Python files decorated with `@udf_tool` and displays their metadata including location, file path, and documentation.

**Examples:**

```bash
# List UDFs in table format
agent-actions list-udfs -u user_code/

# Output as JSON
agent-actions list-udfs -u user_code/ --json

# Show full details (signatures, docstrings)
agent-actions list-udfs -u user_code/ --verbose
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
Use this command to verify which UDFs were discovered and registered from your code directory.
:::

### `validate-udfs`

Validate all UDF references in config without running the workflow.

```bash
agent-actions validate-udfs -a <agent> -u <user-code-path> [options]
```

**Arguments:**
- `-a`, `--agent` - Agent configuration file name (required)
- `-u`, `--user-code` - Path to user code directory containing UDFs (required)

**Options:**
- `--debug` - Enable debug mode
- `-v`, `--verbose` - Enable verbose output

**Description:**

Discovers UDFs from the user code directory and verifies that all `impl` references in the agent configuration exist and are properly decorated with `@udf_tool`. This helps catch configuration errors before running workflows.

**What it validates:**
- All `impl` references exist in the UDF registry
- No duplicate function names across files
- All Python files can be imported without errors
- Functions are properly decorated with `@udf_tool`

**Examples:**

```bash
# Validate agent config references
agent-actions validate-udfs -a my_agent -u user_code/
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
Run this command before deploying workflows to catch UDF reference errors early. Ideal for CI/CD pipelines.
:::

## Error Messages

Agent Actions provides user-friendly error messages designed for configuration authors.

### Without Debug Mode (Default)

Clean, actionable error messages:

```
Configuration Error: Invalid model specified

  Agent: my-agent
  Field: model
  Value: claude-sonnet-4-20250514
  Issue: This model is not available for provider 'anthropic'

  Available models:
  • claude-3-5-sonnet-20241022
  • claude-3-5-haiku-20241022
  • claude-3-opus-20240229

  Fix: Update your agent config:

  model_vendor: anthropic
  model_name: claude-3-5-sonnet-20241022
```

### With Debug Mode

Detailed technical information for developers:

```
Configuration Error: Invalid model specified
  [... user-friendly message ...]

--- Debug Information ---

Exception Chain:
Level 1: ConfigurationError - Invalid model specified
  Context: {
    'agent': 'my-agent',
    'field': 'model',
    'file_path': 'agents/my-agent.yaml',
    'operation': 'load_config',
    'timestamp': '2025-01-27T10:30:00Z'
  }

Level 2: ValueError - Model 'claude-sonnet-4-20250514' not found
  Context: {
    'provider': 'anthropic',
    'available_models': [...]
  }

Full Traceback:
Traceback (most recent call last):
  File "agent_actions/core/config.py", line 123, in load_config
    validate_model(config['model'])
  ...
```

## Logging Levels

Agent Actions adjusts logging based on flags:

| Flag | Level | Shows |
|------|-------|-------|
| None | `CRITICAL` | Only critical system errors |
| `--verbose` | `INFO` | Progress and status updates |
| `--debug` | `DEBUG` | All internal operations + structured logs |

## Environment Variables

Agent Actions respects these environment variables:

- `ANTHROPIC_API_KEY` - Anthropic API key
- `OPENAI_API_KEY` - OpenAI API key
- `AGENT_ACTIONS_ENV` - Environment (dev/staging/prod)

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Usage error (invalid arguments) |
| `130` | Interrupted by user (Ctrl+C) |

## Examples

### Basic Workflow Execution

```bash
agent-actions run product-pipeline.yaml
```

### Debug Configuration Issues

```bash
agent-actions run product-pipeline.yaml --debug
```

This will show:
- Full exception chains
- Configuration loading details
- File path context
- Operation timestamps

### Monitor Long-Running Workflows

```bash
agent-actions run large-batch.yaml --verbose
```

### Check Version

```bash
agent-actions --version
```

### Get Help

```bash
# General help
agent-actions --help

# Command-specific help
agent-actions run --help
agent-actions batch --help
```

## Best Practices

### Development
- Use `--debug` when developing new workflows
- Check exception chains to understand error sources
- Review structured logs for context issues

### Production
- Run without flags for clean output
- Capture logs to monitoring systems
- Use exit codes for automation

### Troubleshooting
1. Start with `--verbose` to see execution flow
2. Use `--debug` to investigate specific errors
3. Check exception chains for root causes
4. Review context information (file paths, agent names, operations)

## See Also

- [Getting Started](./getting-started.md) - First workflow tutorial
- [Core Concepts](./core-concepts/) - Understanding workflows and agents
- [Installation](./installation.md) - Setup instructions

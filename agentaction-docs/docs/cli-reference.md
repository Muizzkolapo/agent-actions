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

## Commands

### `run`

Execute an agent workflow.

```bash
agent-actions run <workflow-file> [options]
```

**Arguments:**
- `<workflow-file>` - Path to YAML workflow configuration

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output
- `--parallel` - Force parallel execution (overrides auto-detection)
- `--no-parallel` - Force sequential execution (overrides auto-detection)
- `--concurrency-limit` - Maximum concurrent agents in parallel execution (default: 5, range: 1-50)

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

### `batch`

Process multiple files in batch mode.

```bash
agent-actions batch <workflow-file> [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

### `test`

Run workflow tests and validations.

```bash
agent-actions test [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

### `clean`

Clean up generated files and caches.

```bash
agent-actions clean [options]
```

### `docs`

Generate documentation for your workflows.

```bash
agent-actions docs [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

### `render`

Render workflow templates.

```bash
agent-actions render <workflow-file> [options]
```

**Options:**
- `--debug` - Enable debug mode
- `--verbose` / `-v` - Enable verbose output

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

  model: claude-3-5-sonnet-20241022
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

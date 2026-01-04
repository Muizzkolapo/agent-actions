# CLI Reference

Agent Actions CLI commands for running workflows and debugging.

## Global Flags

| Flag | Description |
|------|-------------|
| `--debug` | Enable debug mode with detailed logging |
| `--verbose` / `-v` | Enable verbose output |
| `--version` / `-V` | Display version |
| `-h` / `--help` | Show help |

## Working Directory

CLI auto-detects project root by searching for `agent_actions.yml`. Run commands from any subdirectory.

```bash
# All work the same:
cd my-project && agac run -a my_workflow
cd my-project/src/utils && agac run -a my_workflow
```

## run

Execute an agent workflow.

```bash
agac run -a <agent-name> [options]
```

**Examples:**

```bash
# Run a workflow
agac run -a my_agent

# Run with upstream dependencies first
agac run -a my_agent --upstream

# Trigger downstream workflows after
agac run -a my_agent --downstream

# Validate only (no execution)
agac run -a my_agent --validate-only

# Force parallel execution
agac run -a my_agent --parallel

# Debug mode
agac run -a my_agent --debug
```

**Options:**

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agent configuration file name (required) |
| `-u, --user_code DIRECTORY` | Path to UDF code folder |
| `--use-tools` | Enable tool usage |
| `--force` | Force execution despite warnings |
| `--validate-only` / `-v` | Run validation only |
| `--debug` | Enable debug mode |
| `--verbose` | Enable verbose output |
| `--parallel` | Force parallel execution |
| `--no-parallel` | Force sequential execution |
| `--concurrency-limit` | Max concurrent agents (1-50, default: 5) |
| `--upstream` | Execute upstream workflows first |
| `--downstream` | Execute downstream workflows after |

## Parallel Execution

Actions at the same dependency level execute concurrently:

```bash
# Auto-detect (default)
agac run -a my_workflow

# Force parallel
agac run -a my_workflow --parallel

# Force sequential
agac run -a my_workflow --no-parallel

# Limit concurrency
agac run -a my_workflow --concurrency-limit 3
```

## Cross-Workflow Execution

```bash
# Run upstream dependencies first
agac run -a downstream_workflow --upstream

# Trigger downstream after completion
agac run -a upstream_workflow --downstream

# Full chain
agac run -a middle_workflow --upstream --downstream
```

## list-udfs

List all registered UDF tools:

```bash
agac list-udfs
```

## validate

Validate configuration without execution:

```bash
# Validate workflow
agac run -a my_workflow --validate-only

# Validate UDF schemas
agac validate --udfs
```

## Debug Mode

```bash
agac run -a my_workflow --debug
```

**Shows:**
- Structured exception chains
- Complete Python tracebacks
- Detailed logging
- File paths, operation names, timestamps

**Example output:**
```
--- Debug Information ---

Exception Chain:
Level 1: ConfigurationError - Invalid model specified
  Context: {'agent': 'my-agent', 'field': 'model'}

Level 2: ValueError - Model 'gpt-5' not found
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AGENT_ACTIONS_DEBUG` | Enable debug (0/1) |
| `AGENT_ACTIONS_LOG_LEVEL` | DEBUG, INFO, WARNING, ERROR |
| `AGENT_ACTIONS_LOG_FORMAT` | human, json |
| `AGENT_ACTIONS_NO_LOG_FILE` | Disable file logging |
| `AGENT_ACTIONS_ENV` | development, staging, production |

```bash
# Example .env
export OPENAI_API_KEY="sk-..."
export AGENT_ACTIONS_LOG_LEVEL="DEBUG"
```

## Common Workflows

```bash
# Development: validate then run
agac run -a my_workflow --validate-only && agac run -a my_workflow

# Debug failing workflow
agac run -a my_workflow --debug --verbose

# CI/CD validation
agac run -a my_workflow --validate-only

# Production: full pipeline
agac run -a final_workflow --upstream
```

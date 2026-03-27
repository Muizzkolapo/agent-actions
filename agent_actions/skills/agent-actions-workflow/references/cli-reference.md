# CLI Reference

Agent Actions CLI commands for running workflows and debugging.

## Global Flags

| Flag | Description |
|------|-------------|
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

# Force parallel execution
agac run -a my_agent --execution-mode parallel
```

**Options:**

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agent configuration file name (required) |
| `-u, --user-code DIRECTORY` | Path to UDF code folder |
| `--use-tools` | Enable tool usage |
| `-e, --execution-mode` | Execution mode: `auto` (default), `parallel`, or `sequential` |
| `--concurrency-limit` | Max concurrent agents (1-50, default: 5) |
| `--upstream` | Execute upstream workflows first |
| `--downstream` | Execute downstream workflows after |

## Parallel Execution

Actions at the same dependency level execute concurrently:

```bash
# Auto-detect (default)
agac run -a my_workflow

# Force parallel
agac run -a my_workflow --execution-mode parallel

# Force sequential
agac run -a my_workflow --execution-mode sequential

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

## render

Compile and display workflow configuration without executing.

```bash
agac render -a <workflow-name> [options]
```

**What it does:**
- Resolves Jinja2 templates and macros
- Loads and inlines schemas from `schema/` directory
- Expands inline schemas to unified format
- Expands versioned actions

**Examples:**

```bash
# See compiled workflow
agac render -a my_workflow

# Use custom templates directory
agac render -a my_workflow -t ./custom_templates
```

**Options:**

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Workflow name (required) |
| `-t, --template-dir TEXT` | Templates directory (default: `./templates`) |

## list-udfs

List all registered UDF tools:

```bash
agac list-udfs -u <tools_path>
```

**Options:**

| Option | Description |
|--------|-------------|
| `-u, --user-code DIRECTORY` | Path to user code directory containing UDFs (required) |
| `--json` | Output as JSON for programmatic use |
| `--verbose` | Show full signatures and docstrings |

## Debugging

Use environment variables for debug-level logging:

```bash
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow
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
# Debug failing workflow
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow

# Production: full pipeline
agac run -a final_workflow --upstream
```

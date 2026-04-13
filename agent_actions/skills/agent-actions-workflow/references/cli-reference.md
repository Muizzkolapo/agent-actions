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

## validate-udfs

Validate that all UDF references in workflow config point to real registered functions.

```bash
agac validate-udfs -a <workflow-name> -u <tools_path>
```

**What it checks:**
- All `impl:` references in the workflow config resolve to `@udf_tool` decorated functions
- No duplicate function names across tool files
- No Python syntax/import errors in UDF modules

**Options:**

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Workflow name (required) |
| `-u, --user-code DIRECTORY` | Path to UDF directory (required) |

**Example output (success):**
```
All UDF references valid
No duplicate function names
Summary:
  - 12 Tools referenced in config
  - 15 Tools discovered and registered
  - All functions found
```

**Example output (failure):**
```
UDF Validation Errors:
  - not_found: Function 'process_data' referenced in config but not registered
  - duplicate: Function 'flatten_records' defined in both tools/shared/utils.py and tools/workflow/transform.py
  - load_error: Failed to import tools/broken_module.py: SyntaxError line 15
```

Run this before `agac run` to catch UDF issues early, especially after renaming functions or reorganizing tool directories.

## batch

Check status of batch jobs:

```bash
agac batch status --batch-id <id>
```

Returns the current status of a batch job: `completed`, `in_progress`, or `failed`.

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

## Batch Mode

Run actions asynchronously via vendor batch APIs for up to 50% cost savings:

```yaml
- name: expensive_classification
  run_mode: batch                      # Default is "online"
  model_vendor: openai
  model_name: gpt-4o-mini
```

**Supported vendors:** OpenAI, Anthropic, Google (Gemini), Groq, Mistral, Ollama

**How it works:**
1. Framework submits all records as a batch job to the vendor
2. Workflow reports "paused - batch job(s) submitted"
3. Re-run `agac run` later — framework polls for completion
4. When batch completes, results are integrated and downstream actions execute

**Mixing batch + online:** Some actions can be batch while others are online. Tool and HITL actions always run synchronously regardless of `run_mode`.

```yaml
actions:
  - name: cheap_extraction
    run_mode: online                   # Fast, immediate
  - name: expensive_scoring
    run_mode: batch                    # Cheaper, 24-hour window
  - name: format_results
    kind: tool                         # Always synchronous
    dependencies: [expensive_scoring]
```

**Batch + reprompt:** Batch mode supports reprompt validation — failed records are resubmitted as a new batch with feedback appended. This adds latency but maintains quality.

## Common Workflows

```bash
# Debug failing workflow
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow

# Production: full pipeline
agac run -a final_workflow

# Validate UDFs before running
agac validate-udfs -a my_workflow -u tools

# Check batch job status
agac batch status --batch-id <id>
```

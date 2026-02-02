---
title: CLI Reference
description: Complete reference for Agent Actions command-line interface
sidebar_position: 1
---

# CLI Reference

The Agent Actions CLI (`agac`) is your primary interface for building and running agentic workflows. Think of it like a conductor's baton for orchestrating LLM actions - you can execute workflows, inspect field dependencies, manage batch processing, and debug issues all from the command line.

Let's explore what `agac` can do for you.

## Global Flags

These flags work with all commands and help you understand what's happening inside your agentic workflows:

### `--debug`

**What happens when an agentic workflow fails?** By default, you get a summary error message. But sometimes you need to see the full picture - which action failed, what context it had, and where exactly things went wrong.

Debug mode gives you complete visibility:

```bash
agac run my-workflow.yaml --debug
```

**Debug mode shows:**
- Structured exception chains with full context
- Complete Python tracebacks for errors
- Detailed logging from all processors
- File paths, operation names, and timestamps

This means you can trace errors from the symptom (a failed action) back to the root cause (a misconfigured field reference, invalid model name, etc.).

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

Verbose mode shows you the agentic workflow's progress as it runs - which actions are executing, what configuration loaded, and how data flows between steps.

```bash
agac run my-workflow.yaml --verbose
# or
agac run my-workflow.yaml -v
```

**Verbose mode shows:**
- Progress updates for each action
- Configuration loading messages
- Action execution status
- File operations and validations

Use verbose mode when you want to monitor progress without the full diagnostic detail of `--debug`.

### `--version` / `-V`

Display the Agent Actions version.

```bash
agac --version
```

### `--quiet` / `-q`

Suppress non-essential output. Useful for scripts and CI/CD pipelines where you only want to see errors.

```bash
agac run -a my_workflow --quiet
```

### `-h` / `--help`

Show help message and available commands.

```bash
agac --help
agac run --help
```

## Working Directory

You might wonder: do I need to be in my project's root directory to run commands?

No - Agent Actions CLI commands automatically detect your project root by searching for `agent_actions.yml`, similar to how git finds `.git` or npm finds `package.json`. This means you can run commands from **any subdirectory** within your project.

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
agac run my-workflow.yaml
# 📁 Project root: .

# From subdirectory
cd my-project/src/utils
agac run my-workflow.yaml
# 📁 Project root: ../..

# From any depth
cd my-project/src/agents/helpers
agac run my-workflow.yaml
# 📁 Project root: ../../../
```

### Not in a Project?

If you're outside a project directory, you'll get a helpful error:

```bash
$ cd /tmp
$ agac run my-workflow.yaml

Error: Not in an Agent Actions project

Could not find 'agent_actions.yml' in current directory or any parent directory.

Current directory: /tmp

Solutions:
  1. Navigate to your Agent Actions project directory
  2. Run 'agac init' to create a new project
```

### Commands That Work Anywhere

These commands don't require being in a project:
- `init` - Create a new project
- `--version` - Show version
- `--help` - Display help

## Commands Overview

Here's what each command does - organized by what you're trying to accomplish:

**Running agentic workflows:**

| Command | Description |
|---------|-------------|
| [`run`](./run) | Execute an agentic workflow |
| [`batch`](./batch) | Manage batch processing operations |

**Inspecting and debugging:**

| Command | Description |
|---------|-------------|
| [`inspect`](./inspect) | Analyze workflow structure, dependencies, and data flow |
| [`schema`](./schema) | Display input/output schemas and analyze field dependencies |
| [`preview`](./preview) | Preview data stored in the SQLite storage backend |
| [`list-tools`](./tools#list-tools) | List discovered tools |
| [`validate-tools`](./tools#validate-tools) | Validate tool references |
| [`render`](./utilities#render) | Render Jinja2 templates (useful for debugging) |

**Project management:**

| Command | Description |
|---------|-------------|
| [`init`](./utilities#init) | Initialize a new project |
| [`clean`](./utilities#clean) | Clean up generated files |
| [`docs`](./utilities#docs) | Generate documentation |
| [`status`](./utilities#status) | Check agentic workflow status |
| [`skills`](./skills) | Install AI assistant skills (Claude Code / Codex) |

## Next Steps

- **[run Command](./run)** - Execute agentic workflows with all available options
- **[batch Commands](./batch)** - Manage batch processing for large-scale operations
- **[preview Command](./preview)** - Inspect data in the SQLite storage backend
- **[Troubleshooting](./troubleshooting)** - Error messages and debugging strategies

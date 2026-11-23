---
title: CLI Reference
description: The reference for the Agent Actions command-line interface (CLI)
sidebar_position: 1
---

# CLI Reference

The Agent Actions command-line interface (CLI) is `agac`. It is the primary interface to build and run workflows. From the command line, you can run workflows, inspect field dependencies, manage batch processing and debug problems. The sections below describe what `agac` can do.

## Global Flags

These flags work with all commands. They help you see what occurs inside your workflows:

### `--version`

Show the Agent Actions version.

```bash
agac --version
```

### `--debug`

Enable debug mode. Debug mode gives verbose logging and the source file and line references.

```bash
agac --debug run -w my_workflow
```

### `-v` / `--verbose`

Enable verbose output.

```bash
agac --verbose run -w my_workflow
```

### `-q` / `--quiet`

Show only warnings and errors. This flag is useful for scripts and CI/CD pipelines when you want to see only the problems.

```bash
agac --quiet run -w my_workflow
```

### `--help`

Show the help message and the available commands.

```bash
agac --help
agac run --help
```

## The Workflow and the Action

Each command that reads a workflow takes its name as `-w` or `--workflow`. `-a` and `--agent` name the same option:

```bash
agac run -w my_workflow
agac dispositions -w my_workflow
agac run -a my_workflow          # the same as -w
```

Each command that reads one action takes its name as `-A` or `--action`:

```bash
agac traces -w my_workflow -A classify_issue
agac dispositions -w my_workflow -A classify_issue
```

In [`traces`](./traces), [`records`](./records) and [`preview`](./preview), `-a` also names the workflow, and `-A` names the action:

```bash
agac records -a my_workflow -A classify_issue
```

### Errors in the Workflow and the Action

If one of these options is missing or wrong, the command prints an error on stderr and stops with exit code 2:

| Cause | Error |
|-------|-------|
| No workflow option, in a command that needs it (including `inspect action` and `inspect context`), other than `inspect` with no subcommand | `Error: Missing option '-w' / '--workflow' / '-a' / '--agent'.` |
| No action option, in `traces` | `Error: Missing option '-A' / '--action'.` |

[`agac inspect`](./inspect), with no subcommand, gives its own error for a missing workflow option:

```text
Error: Missing required option '-w' / '--workflow'. Run 'agac inspect --help' for usage.
```

Before each `Error:` line, the command also prints a log line on stderr in the form `HH:MM:SS | Usage error: <the same text>`.

## Working Directory

You do not have to be in the root directory of your project to run commands.

The CLI commands find the project root automatically. They search for `agent_actions.yml`. Git finds `.git` and npm finds `package.json` in the same way. Thus you can run commands from **any subdirectory** in your project.

### How It Works

The CLI starts in your current directory. It searches each parent directory in turn for `agent_actions.yml`:

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
agac run -w my_workflow

# From subdirectory
cd my-project/src/utils
agac run -w my_workflow
# 📁 Project root: /path/to/my-project

# From any depth
cd my-project/src/agents/helpers
agac run -w my_workflow
# 📁 Project root: /path/to/my-project
```

From the project root, the command prints no banner. From a subdirectory, the command prints the `📁 Project root:` line on stderr. The line gives the absolute path of the project root.

### Outside a Project {/* #not-in-a-project */}

If you are outside a project directory, the command stops with a `ProjectNotFoundError`:

```bash
$ cd /tmp
$ agac inspect -w my_workflow

Error: Operation Failed: command

  Problem: ProjectNotFoundError: Project not found

  Context:
    search_path: /tmp

  Fix: Check your configuration and try again. Run with --verbose for the full traceback, or check logs/events.json for details.

  Learn more: https://docs.runagac.com/troubleshooting
```

### Commands That Work Anywhere

These commands do not require a project:
- `init`: Create a new project
- `--version`: Show the version
- `--help`: Show the help

## Commands Overview

The tables give each command, in groups by the purpose of the command:

**Run workflows:**

| Command | Description |
|---------|-------------|
| [`run`](./run) | Run a workflow |
| [`batch`](./batch) | Manage batch processing operations |

**Inspect and debug:**

| Command | Description |
|---------|-------------|
| [`inspect`](./inspect) | Preflight checks and introspection: validation, plus the action list with the `dependencies`, `action` and `context` drill-downs |
| [`schema`](./schema) | Show the input and output schemas and analyze the field dependencies |
| [`preview`](./preview) | Show the data in the SQLite storage backend |
| [`traces`](./traces) | Print the prompt, the context and the response that each record of an action used |
| [`records`](./records) | Print, as JSON, the records that an action stored, or the input of each failed record |
| [`dispositions`](./dispositions) | Inspect the processing disposition of each record, for each action |
| [`expect`](./expect) | Show the expectation rules that each action would run, and report the verdicts that a run stored |
| [`usage`](./usage) | Show the tokens that the model calls of each action used, and an estimated cost |
| [`retry`](./retry) | Retry the failed or exhausted records, from a specified action to the end of the workflow |
| [`list-udfs`](./tools#list-udfs) | List discovered tools |
| [`validate-udfs`](./tools#validate-udfs) | Validate tool references |

**Manage the project:**

| Command | Description |
|---------|-------------|
| [`init`](./utilities#init) | Initialize a new project |
| [`example`](./utilities#example) | Find and install example projects from GitHub |
| [`clean`](./utilities#clean) | Remove the working directories of a workflow (output and staging only if you select them) |
| [`docs`](./utilities#docs) | Generate documentation |
| [`status`](./utilities#status) | Show the status of a workflow |
| [`skills`](./skills) | Install AI assistant skills (Claude Code or Codex) |

## Next Steps

- **[run Command](./run)**: Run workflows, with all the available options
- **[batch Commands](./batch)**: Manage batch processing for large operations
- **[preview Command](./preview)**: Inspect the data in the SQLite storage backend
- **[Troubleshooting](./troubleshooting)**: Error messages and debug methods

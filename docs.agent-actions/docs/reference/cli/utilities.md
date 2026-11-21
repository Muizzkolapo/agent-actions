---
title: Utility Commands
description: More CLI commands to set up, debug and maintain a project
sidebar_position: 4
---

# Utility Commands

`agac` runs workflows. It also has commands for project setup, debugging and maintenance. These utility commands initialize projects, help you debug template rendering, run tests and keep your workspace clean.

## render / compile

There are no standalone `agac render` or `agac compile` commands. Rendering occurs implicitly during the preflight checks.
When [`agac inspect`](./inspect) loads a workflow, it expands the templates with Jinja2 and
resolves the prompts. It also puts the schemas inline and expands the versions. If rendering fails,
the command exits with a non-zero code. When the rendered text is not valid YAML, the
command also writes the text to
`.agent-actions/cache/rendered_workflows/<workflow>_failed.yml` for
debugging.

To create the project folders, use [`agac init`](#init).

## init

Use the `init` command to start a new Agent Actions project from the beginning. The command creates an organized directory structure with all the standard folders that you will need.

```bash
agac init <project-name> [options]
agac init list
agac init example <name> [project-name]
```

The command creates this structure:

```
my-project/
├── agent_actions.yml      # Project configuration (required marker file)
├── agent_workflow/        # Agentic workflow definitions
├── schema/                # JSON schemas for validation
├── prompt_store/          # Prompt templates
├── templates/             # Jinja2 templates for config rendering
├── tools/                 # Custom tools
└── seed_data/             # Static reference data
```

The command gives you a working start point with sensible defaults. It is similar to `npm init` or `git init`.

**Subcommands:**
| Subcommand | Description |
|------------|-------------|
| `new <project-name>` | Create a project from a template. This is the default when the first word is not a subcommand |
| `list` | List the available example projects from GitHub |
| `example <name> [project-name]` | Create a project from a GitHub example. This subcommand accepts `-o, --output-dir` and `-f, --force` |

**Options (for `agac init <project-name>`):**
| Option | Description |
|--------|-------------|
| `-o, --output-dir` | The directory in which to create the project (default: the current directory) |
| `-t, --template` | The template name: `default`, `minimal` or `full` (default: `default`). The three templates create the same structure |
| `-f, --force` | Create the project, even if the directory exists |

**Examples:**
```bash
# Create a new project in the current directory
agac init my_project

# Create a project in a specific directory
agac init my_project -o ~/projects

# Name a template (default, minimal or full)
agac init my_project -t minimal

# See all available examples
agac init list

# Scaffold from a GitHub example
agac init example contract_reviewer

# Scaffold from an example with a custom project name
agac init example contract_reviewer my_project

# Force overwrite existing files
agac init my_project -f
```

To start from an example, do these steps:

1. Run `agac init list` to see the available examples.
2. Run `agac init example <name>` to create a fully working project. You can run the project immediately.

:::note[Start from an Example]
The command gets the examples from GitHub. Thus the package stays small.
:::

## example

The `example` command lists and installs example projects from GitHub. It gives the same catalog as `agac init list` / `agac init example`, as a standalone command group.

```bash
agac example list
agac example install <name> [project-name] [options]
```

**Subcommands:**
| Subcommand | Description |
|------------|-------------|
| `list` | List the available example projects from GitHub |
| `install <name> [project-name]` | Install an example project from GitHub |

**Options for `install`:**
| Option | Description |
|--------|-------------|
| `-o, --output-dir TEXT` | The directory in which to create the project (default: the current directory) |
| `-f, --force` | Create the project, even if the directory exists |

**Examples:**
```bash
# See what's available
agac example list

# Install an example under its own name
agac example install contract_reviewer

# Install an example as a custom-named project
agac example install contract_reviewer my_project
```

## clean

The `clean` command removes the working directories of a workflow under `agent_io/`. By default, it removes only `agent_io/source/`. The framework does not write this directory. Thus, on a project without this directory, a plain `clean` finds nothing to remove. The command does not touch your staged input. It removes other items only if you select them with an option.

If `clean` finds something to remove during a run or a retry of the workflow, it removes nothing. It exits 1 with `Another run of workflow '<workflow>' is in progress` (see [Concurrent runs](./run.md#concurrent-runs)). `clean` holds the same lock from before it asks for confirmation until it finishes. It keeps the lock file. After `--all`, `agent_io/store/` holds only the empty `<workflow>.db.lock`.

```bash
agac clean -w <workflow-name> [options]
```

The command removes these items:
- `agent_io/source/`: The framework does not write this directory. The command removes it if it is present (always).
- `agent_io/target/`: Your generated output (only with `--target` or `--all`).
- `agent_io/staging/` and the durable store: Your input data and run history (only with `--all`).
- The data that a provider recorded locally about the batches of this workflow, under `.agac/` at the project root (only with `--all`). Only the store that the command removes names this data. Thus this is the last time that anything can get to the data.

**Options:**
| Option | Description |
|--------|-------------|
| `-w, --workflow TEXT` | The workflow name (required). `-a` and `--agent` name the same option. |
| `-f, --force` | Skip the interactive confirmation |
| `--target` | Also remove `agent_io/target/`, your generated output |
| `--all` | Remove all directories, which include target, staging and the durable store. Also remove the data that a provider recorded locally about the batches of this workflow. You cannot recover the removed data |

**Examples:**
```bash
# Remove regenerable preprocessed inputs (with confirmation)
agac clean -w my_workflow

# Also remove generated output
agac clean -w my_workflow --target

# Remove everything, including staging inputs and the durable store
agac clean -w my_workflow --all
```

:::note[Run from Anywhere]
You can run this command from any subdirectory in your project.
:::

:::danger[WARNING]
If you did not retrieve the batch results yet, retrieve them before you clean. `--target` deletes your generated output. `--all` also deletes the staging inputs and the durable store. You cannot recover any of this data.
:::

## docs

Build and serve interactive documentation for your workflows. In one step, the `docs` command scans your project, generates the documentation data and starts an HTTP server.

The documentation lists an [optional observe field](../context/context-scope.md#optional-fields) as a plain input of the action, without the `?`.

```bash
agac docs [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-o, --output` | The output directory for the generated files. A relative path is relative to the project root (default: `artefact`) |
| `-p, --port` | The port of the server (default: `8000`) |

**Examples:**
```bash
# Build and serve documentation on default port
agac docs

# Serve on a custom port
agac docs --port 3000

# Generate to a custom directory
agac docs --output ./custom-artefact
```

### docs test

Run Playwright tests to verify that the documentation site renders correctly.

```bash
agac docs test [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-t, --test` | The test suite to run: `schemas`, `actions` or `all` (default: `all`) |
| `-p, --port` | The port of the running docs server (default: `8890`) |

The command does not start a server. It needs Node.js, a running docs server, and the test scripts (`test-all-schemas.js`, `test-run-actions-complete.js`, `test-actions-specific.js`) in the project root.

:::note[Run from Anywhere]
You can run docs commands from any subdirectory in your project.
:::

## status

Show the execution status of a specified workflow. The status shows which actions are running, completed or failed.

An action can fail as a whole, with the error in its status (`error_message` in `agent_io/.agent_status.json`). For such an action, an **Error** column shows the first line of that error next to the action. The command cuts the line to 200 characters. The column shows only when a failed action has an error message. This command does not list the failures of single records. For those, see [`agac dispositions`](./dispositions) or [`agac retry --dry-run`](./retry).

```bash
agac status -w <workflow-name> [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-w, --workflow TEXT` | The workflow name (required). `-a` and `--agent` name the same option. |
| `--json` | Print the status of each action and the status of the run as one JSON document |

**Example:**
```bash
agac status -w my_workflow
```

**JSON output:**

`--json` prints one JSON document on stdout, and nothing else. Warnings go to stderr.

```bash
agac status -w my_workflow --json
```

```json
{
  "workflow": "my_workflow",
  "run_status": "FAILED",
  "actions": [
    { "name": "extract", "status": "completed", "error": null },
    { "name": "summarize", "status": "failed", "error": "the error that stopped the action" }
  ]
}
```

The shape is stable. A later release can add a key, but it does not rename or remove one.

| Key | Value |
|-----|-------|
| `workflow` | The workflow name |
| `run_status` | The status that [`agac run`](./run) gives to a run with these action statuses: `SUCCESS`, `FAILED` or `PAUSED`. It is `null` when no action status is stored, because the workflow did not run. Then the command also prints a message on stderr. See the text below this table |
| `actions` | One object for each action in `agent_io/.agent_status.json`, in the order of the file |
| `actions[].name` | The action name. The table shows it in the **Agent Name** column |
| `actions[].status` | The **Status** column: `pending`, `running`, `batch_submitted`, `checking_batch`, `completed`, `completed_with_failures`, `failed`, `skipped` or `interrupted`. It is `null` where the table shows `N/A` |
| `actions[].error` | The full error message of a failed action, or `null`. The **Error** column of the table shows only its first line |

`run_status` has these values:

- `SUCCESS`: Each action completed. An action that completed with failed records (`completed_with_failures`) is also a completed action. To count the failed records, use [`agac dispositions --json`](./dispositions#json-output).
- `FAILED`: Each action ended, and one or more actions failed.
- `PAUSED`: One or more actions did not end. The run is in progress, or it waits for a batch, or it stopped early.

`run_status` is `PAUSED` also while a run is in progress. Thus `run_status` cannot tell a running workflow from a paused one. A monitor must read `actions[].status` for this, for example to find an action with the status `running`.

If the status file holds no action status, the command prints this message and stops with exit code 0. An empty status file (`{}`) gives the same message. With `--json`, the message goes to stderr, and stdout has the document with `run_status` set to `null`. Without `--json`, the message goes to stdout:

```text
No action status is stored for workflow 'my_workflow'. Has it been run?
```

If the status file holds a status that is not in the list above, the command stops with exit code 1. The command does this also for a status file that is not valid JSON. The error names the file and the action:

```text
Error: Status file is corrupted: <project>/agent_workflow/my_workflow/agent_io/.agent_status.json
Action 'summarize' has an unknown status: 'weird'
```

Each action entry in the status file must be a JSON object. If an entry is not an object, for example `"summarize": "completed"`, the command stops with exit code 1 and gives this error:

```text
Error: Status file is corrupted: <project>/agent_workflow/my_workflow/agent_io/.agent_status.json
Action 'summarize' is not an object: 'completed'
```

`agac run`, `agac dispositions`, `agac schema` and `agac retry --dry-run` also stop on such an entry, with exit code 1 and the same two lines in their error. These four commands also stop on a status file that is not a JSON object, for example `[1]` or `null`. `agac status` stops on such a file too. The error for such a file is:

```text
Status file has unexpected format (expected JSON object): <project>/agent_workflow/my_workflow/agent_io/.agent_status.json
```

In `run`, `dispositions`, `schema` and `retry`, the error tells you to edit the status file or to start again with `agac run --fresh`. `agac run --fresh` does not stop on these files. It clears the status file and starts again.

The command reads only the status file. It does not read the workflow configuration. Thus an action that you removed from the configuration stays in the output until `agac run --fresh` clears the file.

:::note[Run from Anywhere]
You can run this command from any subdirectory in your project.
:::

## See Also

- **[run Command](./run)**: Run workflows
- **[batch Commands](./batch)**: Manage batch processing
- **[schema Command](./schema)**: Analyze the structure of a workflow

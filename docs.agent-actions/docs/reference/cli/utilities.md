---
title: Utility Commands
description: Additional CLI commands for project management
sidebar_position: 4
---

# Utility Commands

Beyond running agentic workflows, `agac` provides commands for project setup, debugging, and maintenance. These utilities help you initialize projects, debug template rendering, run tests, and keep your workspace clean.

## render / compile (removed)

`agac render` and `agac compile` are no longer available as standalone
commands. Rendering happens implicitly during preflight — when
[`agac inspect`](./inspect) loads a workflow it Jinja2-expands templates,
resolves prompts, inlines schemas, and expands versions. A rendering
failure surfaces a non-zero exit and writes the partial YAML to
`.agent-actions/cache/rendered_workflows/<workflow>_failed.yml` for
debugging.

If you need fresh scaffolding (the prior `--create-dirs` use case), use
[`agac init`](#init).

## init

Starting a new Agent Actions project from scratch? The `init` command creates a well-organized directory structure with all the standard folders you'll need.

```bash
agac init <project-name> [options]
agac init list
agac init example <name> [project-name]
```

This creates:

```
my-project/
├── agent_actions.yml      # Project configuration (required marker file)
├── agent_workflow/        # Agentic workflow definitions
├── schema/                # JSON schemas for validation
├── prompt_store/          # Prompt templates
└── tools/                 # Custom tools
```

Think of this like `npm init` or `git init` - it gives you a working starting point with sensible defaults.

**Subcommands:**
| Subcommand | Description |
|------------|-------------|
| `list` | List available example projects from GitHub |
| `example <name> [project-name]` | Scaffold from a GitHub example |

**Options (for `agac init <project-name>`):**
| Option | Description |
|--------|-------------|
| `-o, --output-dir` | Directory to create the project in (default: current directory) |
| `-t, --template` | Template to use for project initialization (default: `default`) |
| `-f, --force` | Force project creation even if directory exists |

**Examples:**
```bash
# Create a new project in the current directory
agac init my_project

# Create a project in a specific directory
agac init my_project -o ~/projects

# Use a specific template
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

:::tip Start from an Example
Use `agac init list` to see available examples, then `agac init example <name>` to scaffold a fully working project you can run immediately. Examples are fetched from GitHub so the package stays lightweight.
:::

## example

The `example` command browses and installs example projects from GitHub. It offers the same catalog as `agac init list` / `agac init example`, as a standalone command group.

```bash
agac example list
agac example install <name> [project-name] [options]
```

**Subcommands:**
| Subcommand | Description |
|------------|-------------|
| `list` | List available example projects from GitHub |
| `install <name> [project-name]` | Install an example project from GitHub |

**Options for `install`:**
| Option | Description |
|--------|-------------|
| `-o, --output-dir TEXT` | Directory to create the project in (default: current directory) |
| `-f, --force` | Force project creation even if directory exists |

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

The `clean` command removes a workflow's working directories under `agent_io/`. By default it removes only `agent_io/source/` — the preprocessed input copies that are rebuilt from `agent_io/staging/` on the next run. Anything beyond that is opt-in.

```bash
agac clean -a <workflow-name> [options]
```

Removes:
- `agent_io/source/` — preprocessed inputs, regenerated on the next run (always)
- `agent_io/target/` — your generated output (only with `--target` or `--all`)
- `agent_io/staging/` and the durable store — your input data and run history (only with `--all`)

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agentic workflow name (required) |
| `-f, --force` | Skip interactive confirmation |
| `--target` | Also remove `agent_io/target/` — your generated output |
| `--all` | Remove all directories including target, staging, and the durable store — unrecoverable |

**Examples:**
```bash
# Remove regenerable preprocessed inputs (with confirmation)
agac clean -a my_workflow

# Also remove generated output
agac clean -a my_workflow --target

# Remove everything, including staging inputs and the durable store
agac clean -a my_workflow --all
```

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

:::warning Data Loss
`--target` deletes your generated output, and `--all` additionally deletes staging inputs and the durable store — none of it recoverable. If you haven't retrieved batch results yet, do that first before cleaning.
:::

## docs

Build and serve interactive documentation for your agentic workflows. The `docs` command scans your project, generates documentation data, and starts an HTTP server in one step.

```bash
agac docs [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-o, --output` | Output directory for generated files (default: `artefact`) |
| `-p, --port` | Port to run server on (default: `8000`) |

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

Run Playwright tests to verify the documentation site renders correctly.

```bash
agac docs test [options]
```

:::tip Run from Anywhere
You can run docs commands from any subdirectory within your project.
:::

## status

Check the execution status of a specific agentic workflow. This shows which actions are running, completed, or failed.

```bash
agac status -a <workflow-name> [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agentic workflow name (required) |

**Example:**
```bash
agac status -a my_workflow
```

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

## See Also

- **[run Command](./run)** - Execute agentic workflows
- **[batch Commands](./batch)** - Manage batch processing
- **[schema Command](./schema)** - Analyze agentic workflow structure

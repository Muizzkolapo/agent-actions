---
title: Utility Commands
description: Additional CLI commands for project management
sidebar_position: 4
---

# Utility Commands

Beyond running agentic workflows, `agac` provides commands for project setup, debugging, and maintenance. These utilities help you initialize projects, debug template rendering, run tests, and keep your workspace clean.

## render

**What does your agentic workflow configuration look like after template expansion?**

When your configuration uses Jinja2 templates and macros, the actual YAML that Agent Actions sees might be quite different from what you wrote. The `render` command shows you the final, expanded configuration without executing it.

```bash
agac render -a <workflow-name> [options]
```

This is particularly helpful when:
- **Debugging template issues** - See exactly what the templates produce
- **Verifying macro expansion** - Check if macros expand as expected
- **Troubleshooting YAML parsing errors** - Identify if templates generate invalid YAML
- **Learning how templates work** - Understand the template-to-config transformation

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agentic workflow name to render (required) |
| `-t, --template-dir TEXT` | Directory containing templates (default: `./templates`) |
| `--debug` | Enable debug mode |
| `--verbose` / `-v` | Enable verbose output |

**Examples:**
```bash
# Render agentic workflow config to console
agac render -a my_workflow

# Render with custom templates directory
agac render -a my_workflow -t custom_templates
```

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

## init

Starting a new Agent Actions project from scratch? The `init` command creates a well-organized directory structure with all the standard folders you'll need.

```bash
agac init [project-name] [options]
```

This creates:

```
my-project/
├── agent_actions.yml      # Project configuration (required marker file)
├── agent_workflow/        # Agentic workflow definitions
├── schema/                # JSON schemas for validation
├── prompt_store/          # Prompt templates
└── tools/                 # Custom UDFs
```

Think of this like `npm init` or `git init` - it gives you a working starting point with sensible defaults.

**Options:**
| Option | Description |
|--------|-------------|
| `--debug` | Enable debug mode |
| `--verbose` / `-v` | Enable verbose output |

## clean

Over time, your project accumulates cached results, generated documentation, and temporary files. The `clean` command removes these artifacts and returns your project to a fresh state.

```bash
agac clean [options]
```

Removes:
- Cached batch results
- Generated documentation
- Temporary files
- Build artifacts

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

:::warning Data Loss
This removes cached batch results. If you haven't retrieved batch results yet, do that first before cleaning.
:::

## docs

Generate documentation for your agentic workflows. This creates markdown files describing your actions, their inputs and outputs, and how they connect.

```bash
agac docs [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `--debug` | Enable debug mode |
| `--verbose` / `-v` | Enable verbose output |

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

## status

Check the execution status of your agentic workflows. This shows which workflows are running, completed, or failed.

```bash
agac status [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `--debug` | Enable debug mode |
| `--verbose` / `-v` | Enable verbose output |

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

## See Also

- **[run Command](./run)** - Execute agentic workflows
- **[batch Commands](./batch)** - Manage batch processing
- **[schema Command](./schema)** - Analyze agentic workflow structure

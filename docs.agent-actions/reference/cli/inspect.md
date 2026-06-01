---
title: inspect Commands
description: Analyze workflow structure and data flow
sidebar_position: 6
---

# inspect Commands

Understanding how your actions connect can be challenging as workflows grow. The `inspect` command group helps you analyze workflow structure, dependencies, and data flow without executing anything.

```bash
agac inspect <subcommand> [options]
```

:::tip Run from Anywhere
You can run inspect commands from any subdirectory within your project.
:::

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `dependencies` | Analyze workflow dependencies and auto-inferred context |
| `graph` | Show workflow structure as a visual dependency graph |
| `action` | Show detailed information about a specific action |
| `context` | Show context debug information for a specific action |

## inspect dependencies

**How do actions connect to each other?**

This command shows the dependency model for your workflow - which actions feed into others and which provide context data.

```bash
agac inspect dependencies -a <workflow-name> [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Workflow name (required) |
| `-u, --user-code` | Path to user code directory |
| `--json` | Output as JSON |
| `--action TEXT` | Filter to a specific action |

**Example:**
```bash
agac inspect dependencies -a my_workflow
```

The output table shows:
- **Input Sources**: Actions that provide the primary input data
- **Context Sources**: Actions that provide additional context (via `context_scope`)
- **Type**: Classification based on dependency pattern (Source, Transform, Merge, etc.)

### Filter to Specific Action

```bash
agac inspect dependencies -a my_workflow --action extract_facts
```

### JSON Output

```bash
agac inspect dependencies -a my_workflow --json
```

## inspect graph

**Visualize the workflow structure**

Shows your workflow as a tree with data flow indicators:

```bash
agac inspect graph -a <workflow-name> [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Workflow name (required) |
| `-u, --user-code` | Path to user code directory |
| `--json` | Output as JSON |

**Example:**
```bash
agac inspect graph -a my_workflow
```

The output symbols indicate:
- **←** Input source (execution dependency)
- **◇** Context source (additional data)
- **→** Output fields (from schema)

## inspect action

**Deep dive into a single action**

Shows detailed configuration, dependencies, and schema for one action:

```bash
agac inspect action -a <workflow-name> <action-name> [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Workflow name (required) |
| `-u, --user-code` | Path to user code directory |
| `--json` | Output as JSON |

**Example:**
```bash
agac inspect action -a my_workflow generate_question
```

### JSON Output

```bash
agac inspect action -a my_workflow generate_question --json
```

## inspect context

**Debug context data availability for an action**

Shows what data namespaces, template variables, and context scope rules would be available during template rendering for a specific action. This helps you understand what data is available without running the workflow.

```bash
agac inspect context -a <workflow-name> <action-name> [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Workflow name (required) |
| `-u, --user-code` | Path to user code directory |
| `--json` | Output as JSON |

**Example:**
```bash
agac inspect context -a my_workflow generate_question
```

The output shows:
- **Namespaces loaded**: Available data namespaces (source, dependencies, versions, workflow)
- **Context scope applied**: Which fields are observed, passed through, or dropped
- **Template variables available**: Variables you can use in your prompt templates
- **Dependencies**: Input sources and context sources

### JSON Output

```bash
agac inspect context -a my_workflow generate_question --json
```

:::tip Debugging Template Errors
If you're getting "undefined variable" errors in your templates, use `inspect context` to see exactly what variables are available for that action.
:::

## Use Cases

### Debugging Dependency Issues

If an action isn't receiving expected data:

```bash
# Check what the action thinks its dependencies are
agac inspect action -a my_workflow problematic_action

# See the full dependency chain
agac inspect graph -a my_workflow
```

### Understanding Execution Order

```bash
# See the computed execution order
agac inspect graph -a my_workflow --json | jq '.execution_order'
```

### Validating context_scope Configuration

```bash
# Check if context fields are correctly inferred
agac inspect dependencies -a my_workflow --json
```

### Debugging Template Variable Issues

```bash
# See what variables are available for an action
agac inspect context -a my_workflow problematic_action

# Check if specific fields are accessible
agac inspect context -a my_workflow problematic_action --json | jq '.namespaces'
```

## See Also

- **[schema Command](./schema)** - Analyze field dependencies and data shapes
- **[run Command](./run)** - Execute agentic workflows
- **[Troubleshooting](./troubleshooting)** - Debug common issues

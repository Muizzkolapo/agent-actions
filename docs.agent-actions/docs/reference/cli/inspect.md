---
title: inspect Commands
description: Workflow preflight and introspection
sidebar_position: 6
---

# inspect Commands

`agac inspect` is the read-only introspection surface for a workflow. The
default form runs preflight validation and renders a dependency graph;
two subcommands drill into a single action.

```bash
agac inspect -a <workflow>                          # default: graph + validation
agac inspect action  -a <workflow> ACTION [options]
agac inspect context -a <workflow> ACTION [options]
```

:::tip Run from Anywhere
You can run inspect commands from any subdirectory within your project.
:::

## Default behavior

`agac inspect -a <workflow>` runs preflight validation and prints a
validated action list — one ✓ per action, one `● validated` badge for
the whole workflow. Exits 0 on success, non-zero on validation error.

```bash
$ agac inspect -a review_analyzer

review_analyzer  ● validated                              5 actions

  ✓  fetch_reviews
  ✓  analyze_sentiment
  ✓  extract_topics
  ✓  generate_summary
  ✓  write_report
```

Preflight covers action definitions, dependency cycles, `context_scope`
references — including that every declared dependency is referenced by
at least one `observe` or `passthrough` field — template variables,
schema structure, and guard syntax. If any static check fails you get
a `PreFlightValidationError` naming the exact YAML field instead of
the list.

For structure, drill down with `inspect action <name>` (deps + prompt
+ schema + who reads this action) or `inspect context <name>`
(template variables that are in scope).

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `action`  | Detailed configuration for a single action |
| `context` | Template-variable debug view for a single action |

Each subcommand accepts its own `--json` flag for machine-readable
output.

### inspect action

```bash
agac inspect action -a <workflow> <action_name> [--json]
```

Configuration, dependencies, context scope, rendered prompt template,
output schema, LLM settings, and downstream consumers for one action.

### inspect context

```bash
agac inspect context -a <workflow> <action_name> [--json]
```

Available namespaces, applied context scope, and template variables the
action's prompt would see.

:::tip Debugging Template Errors
If you're getting "undefined variable" errors in your templates, use
`inspect context` to see exactly what variables are available for that
action.
:::

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Inspection OK (graph shown, validation passed) |
| 1 | Validation failed or other CLI error |
| 2 | Bad flags or missing required option |

## Common patterns

### Dependency debugging

The default `agac inspect -a my_workflow` shows the full dependency
graph with parallel fan-outs. For per-action drill-down with inputs,
context, schema, and rendered prompt:

```bash
agac inspect action -a my_workflow problematic_action
```

### Validate before run (in CI)

```bash
agac inspect -a my_workflow || exit 1
agac run     -a my_workflow
```

### Template-variable debug

```bash
agac inspect context -a my_workflow problematic_action
agac inspect context -a my_workflow problematic_action --json | jq '.namespaces'
```

## See Also

- **[schema Command](./schema)** - Analyze field dependencies and data shapes
- **[run Command](./run)** - Execute agentic workflows
- **[Troubleshooting](./troubleshooting)** - Debug common issues

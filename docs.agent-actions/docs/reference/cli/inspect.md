---
title: inspect Commands
description: Unified workflow preflight and introspection
sidebar_position: 6
---

# inspect Commands

`agac inspect` is the single preflight and introspection surface. Use it
to render the rendered workflow YAML, validate it, dry-run estimates, or
explore the dependency graph — without touching storage or the LLM.

```bash
agac inspect -a <workflow> [--yaml|--validate|--dry-run] [--json]
agac inspect <subcommand> -a <workflow> [options]
```

:::tip Run from Anywhere
You can run inspect commands from any subdirectory within your project.
:::

## Default behavior (no flag)

Shows the dependency graph with validation status:

```bash
$ agac inspect -a review_analyzer

✅ Workflow: review_analyzer

Actions
├── Level 1
│   └── fetch_reviews (observe)
├── Level 2
│   ├── analyze_sentiment (drop=2)
│   └── extract_topics (drop=2)
└── Level 3
    ├── generate_summary (observe)
    └── write_report (passthrough=1)
```

## Flags

### `--yaml`

Output the rendered workflow YAML. Replaces the removed `agac compile`
and `agac render` commands.

```bash
$ agac inspect -a my_workflow --yaml > rendered.yml
```

The output is post-template-expansion, post-prompt-resolution, and
post-schema-inlining — the same YAML the runtime would consume.

### `--validate`

Validation report only (pass/fail). Exits 0 on success, non-zero on
failure. Useful in CI:

```bash
$ agac inspect -a my_workflow --validate
✅ my_workflow: validation passed

$ agac inspect -a broken_workflow --validate
❌ broken_workflow: validation failed
schema: Action 'analyze_sentiment': Could not load schema 'sentiment.yml'
```

### `--dry-run`

Full preflight: dependency graph + validation + resource estimate.

```bash
$ agac inspect -a my_workflow --dry-run
Preflight: my_workflow

Execution levels:
  Level 1: fetch_reviews
  Level 2: analyze_sentiment, extract_topics
  Level 3: generate_summary, write_report

Context scope:
  fetch_reviews     → {'observe': [...], 'drop': [...]}
  analyze_sentiment → {'observe': [...], 'drop': [...]}

Estimate: 5 actions, 4 LLM calls, 2 guarded

✅ Validation passed
```

### `--json`

Output JSON instead of rich text. Combines with the other modes.

```bash
$ agac inspect -a my_workflow --json
{
  "workflow": "my_workflow",
  "validation_ok": true,
  "execution_levels": [["fetch_reviews"], ["analyze_sentiment", "extract_topics"]],
  "context_scope": { "fetch_reviews": { "scope": "observe" }, ... }
}
```

:::tip Validation never hits the network
The bare `agac inspect` (and `--validate`, `--dry-run`) runs preflight
with `verify_keys=False`, so the LLM-vendor key-probing endpoint is
skipped. Use `agac run --verify-keys` if you want to confirm keys are
live.
:::

### Flag mutual exclusion

`--yaml`, `--validate`, and `--dry-run` are mutually exclusive — pass
exactly one (or none for the default graph). `--json` combines with any
of them.

## Subcommands

The original deep-dive subcommands are still available unchanged.

| Subcommand | Description |
|------------|-------------|
| `dependencies` | Dependency analysis table |
| `graph` | Visual dependency tree (alternative to default) |
| `action` | Detailed configuration for a single action |
| `context` | Template-variable debug view for a single action |

### inspect dependencies

```bash
agac inspect dependencies -a <workflow> [--action <name>] [--json]
```

Shows input sources (execution dependencies) and context sources
(auto-inferred from `context_scope`) per action.

### inspect graph

```bash
agac inspect graph -a <workflow> [--json]
```

Identical to the default `agac inspect -a <workflow>` view.

### inspect action

```bash
agac inspect action -a <workflow> <action_name> [--json]
```

Configuration, dependencies, context scope, and resolved output fields
for one action.

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
| 0 | Inspection OK (graph shown, validation passed or skipped) |
| 1 | Validation failed (`--validate` / `--dry-run`), or other CLI error |
| 2 | Bad flags or missing required option |

## Migration from `agac compile` / `agac render`

```bash
# Before (removed)
agac compile -a my_workflow > rendered.yml
agac render  -a my_workflow > rendered.yml

# After
agac inspect -a my_workflow --yaml > rendered.yml
```

The `-t/--template-dir` and `--create-dirs` flags from the old commands
have no equivalent under `agac inspect` — introspection is read-only, so
it never creates directories. If you depended on `--create-dirs`,
`agac init` is the right command for first-time scaffolding.

## Common patterns

### Dependency debugging

```bash
agac inspect action -a my_workflow problematic_action
agac inspect graph  -a my_workflow
```

### Execution order

```bash
agac inspect -a my_workflow --json | jq '.execution_levels'
```

### Validate before run (in CI)

```bash
agac inspect -a my_workflow --validate || exit 1
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

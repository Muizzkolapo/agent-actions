---
title: inspect Commands
description: Run the preflight checks of a workflow and show its structure
sidebar_position: 6
---

# inspect Commands

`agac inspect` is the read-only command that shows the structure of a workflow. The
default form runs the preflight validation and lists the validated actions.
Two subcommands show the details of a single action.

```bash
agac inspect -a <workflow>                          # default: validation + action list
agac inspect action  -a <workflow> ACTION [options]
agac inspect context -a <workflow> ACTION [options]
```

:::note[Run from Anywhere]
You can run inspect commands from any subdirectory in your project.
:::

## Options

| Option | Description |
|--------|-------------|
| `-a`, `--agent` | The workflow name. Required. Without it, `agac inspect` exits 2 with `Missing required option '-a' / '--agent'. Run 'agac inspect --help' for usage.` |
| `-u`, `--user-code` | The path to the user code directory. `inspect action` and `inspect context` also accept this option |

## Default Behavior {/* #default-behavior */}

`agac inspect -a <workflow>` runs the preflight validation and prints a
list of the validated actions. The list has one ✓ for each action, and one `● validated` badge for
the whole workflow. The command exits 0 on success. It exits with a non-zero code on a validation error.

```bash
$ agac inspect -a review_analyzer

review_analyzer  ● validated                              5 actions

  ✓  fetch_reviews
  ✓  analyze_sentiment
  ✓  extract_topics
  ✓  generate_summary
  ✓  write_report
```

The preflight validation checks these items:

- Action definitions
- Dependency cycles
- `context_scope` references. This check includes two conditions:
  - At least one `observe` or `passthrough` field refers to each declared dependency.
  - Each action that a `context_scope`, a prompt or a guard names is upstream of it through
    `dependencies`.
- Template variables
- Schema structure
- Each schema that an action names
  by file exists and loads. This check applies to LLM actions and tool actions.
- Guard syntax
- Each `action_name.field` that a prompt or a guard reads names an action in the workflow and a field that its
  schema lists.

If a static check fails, you get
a `PreFlightValidationError` that names the exact YAML field. You do not get
the list.

The command prints a finding that does not stop the run above the list, as a
warning. The command still exits 0. `agac run` prints the same
warnings before it starts. The command prints each finding one time, in a group with the other findings of the same
check:

```text
Pre-flight: static analysis — 1 warning(s)
  └─ assign_team: Action 'assign_team': seed field 'routing_rules' is both in
context_scope.observe and referenced in the prompt template ...
```

To see the structure, use `inspect action <name>` or `inspect context <name>`.
`inspect action <name>` shows the dependencies, the prompt, the schema and the actions that read this action.
`inspect context <name>` shows the template variables that are in scope.

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `action`  | The detailed configuration of a single action |
| `context` | A view of the template variables of a single action, for debugging |

Each subcommand accepts its own `--json` flag for output that a machine can read.

### inspect action

```bash
agac inspect action -a <workflow> <action_name> [--json]
```

This subcommand shows these items for one action:

- The configuration
- The dependencies
- The context scope
- The prompt template, with no values in its field references
- The output schema
- The model and run settings
- The downstream actions that use the action

### inspect context

```bash
agac inspect context -a <workflow> <action_name> [--json]
```

This subcommand shows the available namespaces, the applied context scope, and the template variables that the
prompt of the action would see.

If you get "undefined variable" errors in your templates, use
`inspect context`. It shows exactly which variables are available for that
action.

## Exit Codes {/* #exit-codes */}

| Code | Meaning |
|------|---------|
| 0 | The inspection is OK (the validation passed, and the command showed the action list) |
| 1 | The validation failed, or a different CLI error occurred |
| 2 | Incorrect flags, or a missing required option |

## Common Patterns {/* #common-patterns */}

### Debug Dependencies {/* #dependency-debugging */}

The default `agac inspect -a my_workflow` validates the workflow and lists
its actions. To see the details of one action, with its inputs, context, schema and
prompt template, use `inspect action`:

```bash
agac inspect action -a my_workflow problematic_action
```

### Validate Before a Run (in CI) {/* #validate-before-run-in-ci */}

```bash
agac inspect -a my_workflow || exit 1
agac run     -a my_workflow
```

### Debug Template Variables {/* #template-variable-debug */}

```bash
agac inspect context -a my_workflow problematic_action
agac inspect context -a my_workflow problematic_action --json | jq '.namespaces'
```

## See Also

- **[schema Command](./schema)**: Analyze field dependencies and the shapes of data
- **[run Command](./run)**: Run workflows
- **[Troubleshooting](./troubleshooting)**: Debug common problems

---
title: expect Command
description: Inspect the expectation rules an action would run
sidebar_position: 9
---

# expect Command

The `expect` commands make the [expectations engine](../validation/expectations.md) visible from outside a run. Rules reach an action by three different routes, and until you run the workflow there is no way to see which ones an action will actually execute.

```bash
agac expect list -a <workflow-name> [options]
```

## `expect list`

Print the rules each action would run.

```bash
agac expect list -a my_workflow
```

```
my_workflow   expectations                                    3 rules across 1 action

summarize  suite summarize:schema · repair auto
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Rule                  ┃ Type               ┃ Field       ┃ Severity ┃ Params         ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ summary_is_present    │ not_null           │ summary     │  error   │ —              │
│ summary_is_sized      │ word_count_between │ summary     │  error   │ max=80, min=10 │
│ density_is_known      │ accepted_values    │ density     │  warn    │ values=[...]   │
└───────────────────────┴────────────────────┴─────────────┴──────────┴────────────────┘
```

### Options

| Option | Description |
|--------|-------------|
| `-a`, `--agent` | Workflow name (required) |
| `--action` | Limit the listing to one action |
| `--json` | Emit the listing as JSON on stdout |

### All three declaration routes print identically

An action gets its rules from an inline `expectations:` list, a named `suite:`, or — for a bare `expect:` block — its own [`schema:` file](../validation/expectations.md#rules-in-the-schema-file). The listing resolves them through the same loader the runner uses, so what you see is what would execute, whichever route the author chose.

The heading names the resolved suite, so you can tell the routes apart: `summarize:inline` for an inline list, the suite's own name for `suite:`, and `summarize:schema` for a bare block reading its schema.

### Rules that will not run

A `kind: tool` or `kind: hitl` action at `granularity: file` is processed by a strategy that does not evaluate expectations. Rules declared on such an action never run. They are still listed — they are authored, and hiding them would not explain their silence — but the entry says so:

```
flatten  suite flatten:schema · repair none
  ⚠ these rules will not run: a tool or HITL action at file granularity is
    processed by a strategy that does not evaluate expectations
```

In `--json`, the same entry carries `"executes": false` and an `"inert_because"` string.

### A refused workflow

`expect list` runs the same preflight `agac run` runs. A workflow it refuses reports the refusal, naming the correction, rather than printing an empty list:

```bash
agac expect list -a my_workflow
# Problem: summarize: unknown_type: unknown type 'vibe_check'. Known types: ...
```

### JSON output

`--json` writes the listing to stdout; diagnostics go to stderr, so the stream stays parseable.

```bash
agac expect list -a my_workflow --json | jq '.actions[] | {action, rules: [.rules[].id]}'
```

```json
{
  "workflow": "my_workflow",
  "actions": [
    {
      "action": "summarize",
      "suite": "summarize:schema",
      "repair": "auto",
      "executes": true,
      "inert_because": null,
      "rules": [
        {
          "id": "summary_is_sized",
          "type": "word_count_between",
          "field": "summary",
          "severity": "error",
          "params": {"min": 10, "max": 80},
          "hint": "Keep it to a short paragraph."
        }
      ]
    }
  ]
}
```

A rule with no authored `id:` is listed under the one the engine derives for it (`{type}_{hash}`), which is the same id that appears in a stored verdict.

## See also

- **[Expectations](../validation/expectations.md)** — authoring the rules this command lists
- **[inspect Command](./inspect)** — workflow structure and preflight status

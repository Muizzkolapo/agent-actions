---
title: usage Command
description: Show the tokens that the model calls of each action used, and an estimated cost
sidebar_position: 8
---

# usage Command

The `usage` command shows, for each action, the model calls that the action made and the tokens that the calls used. With a price table, the command also shows an estimated cost.

```bash
agac usage -a <workflow-name> [options]
```

The command reads the sums that each run keeps in the durable store. It opens the store read-only, so you can use it while a run is in progress. A run writes the sum of an action when the action stops. While the action runs, the run writes the sum again after about 10 seconds, at the next model call.

## Options

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | The name of the agent configuration file, with no path or extension (required) |
| `--run TEXT` | Show one run only. The value is the `id` of the run in `artefact/runs.json`. If you omit it, the command adds all the runs. |
| `--json` | Print the report as JSON |

## Output

The output has one row for each action, kind of call, pricing and model. The last row is the total.

```
                                          Usage: my_workflow (3 runs)
┃ Action  ┃ Kind   ┃ Pricing ┃ Model            ┃ Calls ┃     Input ┃ Cache read ┃ Cache write ┃  Output ┃ Est. cost ┃
│ extract │ main   │ batch   │ claude-haiku-5-5 │   120 │    96,000 │    410,000 │       4,100 │  31,000 │    0.1486 │
│ write   │ main   │ online  │ claude-haiku-5-5 │   120 │   212,000 │          0 │           0 │  64,000 │    0.5320 │
│ write   │ repair │ online  │ claude-haiku-5-5 │    14 │    31,000 │          0 │           0 │   7,500 │    0.0685 │
│ write   │ judge  │ online  │ claude-haiku-5-5 │   670 │   905,000 │          0 │           0 │  40,200 │    1.1060 │
│ write   │ all    │         │                  │   804 │ 1,148,000 │          0 │           0 │ 111,700 │    1.7065 │
│ Total   │        │         │                  │   924 │ 1,244,000 │    410,000 │       4,100 │ 142,700 │    1.8551 │
```

| Column | Meaning |
|--------|---------|
| `Kind` | `main` is the call that the action makes for a record. A retry of that call is also `main`. `repair` is a call that an `expect:` repair makes. `judge` is a call that an `llm_judge` rule makes, one for each vote. Other side calls show the name of their kind. `all` is the sum for an action that has more than one row. |
| `Pricing` | `online` or `batch`. A call that a provider batch answered is `batch`. A judge call that a batch action sends as a batch is `judge` and `batch`. |
| `Model` | The model that the call named. A judge with its own `model` has its own row. |
| `Calls` | The number of calls that the provider answered. A call that failed before an answer is not in the count. |
| `Input` | The prompt tokens that the provider did not read from its cache and did not write to its cache. |
| `Cache read` | The prompt tokens that the provider read from its prompt cache |
| `Cache write` | The prompt tokens that the provider wrote to its prompt cache |
| `Output` | The output tokens. For Gemini, this includes the thinking tokens. |
| `Est. cost` | The estimated cost. The column shows only when `agent_actions.yml` has a `prices:` block. |

The sum of `Input`, `Cache read` and `Cache write` is the full prompt. A provider that reports no cached tokens shows 0 in the two cache columns. A provider that reports no usage shows the calls with 0 tokens.

### Runs in the Sum

Without `--run`, the command adds all the runs that the store holds. Thus a batch action shows one sum for the run that submitted the batch and the runs that collected it. The command counts each batch one time. If a later run reads a batch again, the batch stays in the sum of the run that read it first.

`agac run --fresh` clears the sums together with the stored results. `artefact/runs.json` keeps the usage of each run, also after `--fresh`. `agac run --rerun <action>` does not clear the sums: the calls of the first run and of the second run are both in the report.

## Estimated cost

Agent Actions has no built-in prices, because a provider can change its prices. To get a cost, add the price of one million tokens for each model to `agent_actions.yml`:

```yaml
prices:
  claude-haiku-5-5:
    input: 1.00           # one million input tokens
    output: 5.00          # one million output tokens
    cache_read: 0.10      # one million tokens read from the prompt cache
    cache_write: 1.25     # one million tokens written to the prompt cache
    batch_discount: 0.5   # a batch call costs 50% less
```

| Key | Description |
|-----|-------------|
| `input`, `output` | Required. A number, 0 or more. |
| `cache_read`, `cache_write` | Optional. Necessary only for a model whose calls use the prompt cache. |
| `batch_discount` | Optional. A number from 0 to 1: the part that the provider removes from the price of a batch call. Necessary only for a model that runs in batch. |

The key of each entry is the `model_name` that the action uses. The `Model` column shows the name to use.

The cost is an estimate. It is not the bill of the provider. The command never shows 0 for a cost that it cannot calculate:

- If a model has no entry, its rows show `-` and the command names the model, for example `prices.gpt-4o-mini`.
- If an entry has no price that a row needs, the row shows `-` and the command names the key, for example `prices.claude-haiku-5-5.batch_discount`.
- A sum that does not include such a row has a `+` after the cost.

Without a `prices:` block, the command shows the tokens only. It tells you that you can add a price table, and names the models of the report.

## JSON

`--json` prints the same report:

```json
{
  "workflow": "my_workflow",
  "runs": ["run_my_workflow_1a2b3c4d", "run_my_workflow_5e6f7a8b"],
  "actions": {
    "write": {
      "calls": 134,
      "input_tokens": 243000,
      "output_tokens": 71500,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 0,
      "estimated_cost": 0.6005,
      "by_kind": [
        {
          "kind": "main",
          "batch": false,
          "model": "claude-haiku-5-5",
          "calls": 120,
          "input_tokens": 212000,
          "output_tokens": 64000,
          "cache_read_input_tokens": 0,
          "cache_creation_input_tokens": 0,
          "estimated_cost": 0.532
        },
        {
          "kind": "repair",
          "batch": false,
          "model": "claude-haiku-5-5",
          "calls": 14,
          "input_tokens": 31000,
          "output_tokens": 7500,
          "cache_read_input_tokens": 0,
          "cache_creation_input_tokens": 0,
          "estimated_cost": 0.0685
        }
      ]
    }
  },
  "total": {
    "calls": 134,
    "input_tokens": 243000,
    "output_tokens": 71500,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "estimated_cost": 0.6005
  },
  "priced": true,
  "unpriced": []
}
```

| Key | Meaning |
|-----|---------|
| `runs` | The runs that the report adds |
| `actions.<name>` | The sum for the action, and one entry in `by_kind` for each kind, pricing and model |
| `estimated_cost` | `null` for a row that the price table cannot price. For an action and for `total`, the sum of the rows that have a cost, or `null` if no row has one. |
| `priced` | `true` if `agent_actions.yml` has a `prices:` block |
| `unpriced` | The keys that the price table needs for the rows that have no cost |

`artefact/runs.json` holds the same five fields and the same `by_kind` list for each action of each run. See [Run History](../execution/artifacts#run-history-runsjson).

## Examples

```bash
# Every run of the workflow
agac usage -a my_workflow

# One run
agac usage -a my_workflow --run run_my_workflow_1a2b3c4d

# For a script
agac usage -a my_workflow --json
```

## Errors

| Message | Cause |
|---------|-------|
| `No store for workflow '<name>' at <path>. Has it been run?` | The workflow did not run. Thus it has no store. |
| `No usage is recorded for run '<id>' of '<name>'` | The run made no model call, or the id is not an id of this workflow. The message gives the runs that have usage. |
| `Configuration validation failed for 'prices': prices.<model>...` | The `prices:` block has an error. The message gives the key and the cause. |

---
title: expect Command
description: Show the expectation rules that an action would run, and the verdicts that a run stored
sidebar_position: 9
---

# expect Command

The `expect` commands show the [expectations engine](../validation/expectations.md) from outside a run. Rules get to an action by three different routes. Until you run the workflow, there is no way to see which rules an action will actually execute.

```bash
agac expect list -a <workflow-name> [options]
```

## `expect list`

Print the rules that each action would run.

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
| `-a`, `--agent` | The workflow name (required) |
| `--action` | Limit the listing to one action |
| `--json` | Write the listing as JSON on stdout |

### The Three Declaration Routes Print Identically {/* #all-three-declaration-routes-print-identically */}

An action gets its rules from one of three sources:

- An inline `expectations:` list
- A named `suite:`
- For a bare `expect:` block, its own [`schema:` file](../validation/expectations.md#rules-in-the-schema-file)

The listing resolves the rules through the same loader that the runner uses. Thus the listing shows what would execute, for any route that the author selects.

The heading names the resolved suite. Thus you can see the difference between the routes:

- `summarize:inline` for an inline list
- The name of the suite for `suite:`
- `summarize:schema` for a bare block that reads its schema

### Rules That Will Not Run {/* #rules-that-will-not-run */}

A strategy that does not evaluate expectations processes a `kind: tool` or `kind: hitl` action at `granularity: file`. Rules that such an action declares never run. The listing still shows them, because the author wrote them, and to hide them would not explain why they give no result. The entry tells you that the rules will not run:

```
flatten  suite flatten:schema · repair none
  ⚠ these rules will not run: a tool or HITL action at file granularity is
    processed by a strategy that does not evaluate expectations
```

In `--json`, the same entry contains `"executes": false` and an `"inert_because"` string.

### A Refused Workflow {/* #a-refused-workflow */}

`expect list` runs the same preflight checks as `agac run`. If the preflight checks refuse a workflow, the command reports the refusal and names the correction. It does not print an empty list:

```bash
agac expect list -a my_workflow
# Problem: PreFlightValidationError: summarize: unknown_type: unknown type 'vibe_check'. Known types: ...
```

### JSON Output {/* #json-output */}

`--json` writes the listing to stdout. Diagnostics go to stderr. Thus the stdout stream stays parseable.

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

If a rule has no authored `id:`, the listing uses the ID that the engine derives for it (`{type}_{hash}`). A stored verdict uses the same ID.

## `expect report`

Read the verdicts that a run stored. Each run writes one verdict for each record. Without this command, you can get the verdicts only if you open the store.

```bash
agac expect report -a my_workflow
```

```
my_workflow   expectation verdicts                           619 records across 10 actions

summarize  412/500 records passed · 82%   ⚠ 3 records carried no verdict
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Rule              ┃ Type               ┃ Severity ┃ Passed ┃ Failed ┃ Skipped ┃ Pass rate ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ summary_is_sized  │ word_count_between │  error   │    412 │     88 │       0 │       82% │
│ summary_grounded  │ llm_judge          │  warn    │    480 │      0 │      20 │      100% │
└───────────────────┴────────────────────┴──────────┴────────┴────────┴─────────┴───────────┘
```

The report sorts the rules by how frequently they failed. Thus the rule that costs an action the most records is first in its table.

### Options

| Option | Description |
|--------|-------------|
| `-a`, `--agent` | The workflow name (required) |
| `--action` | Limit the report to one action |
| `--json` | Write the report as JSON on stdout |
| `--fail-under` | Exit with a non-zero code if the pass percentage of any action is less than this value |

### How the Counts Are Calculated {/* #how-the-counts-are-arrived-at */}

- **Passed / Failed** count the records on which a rule actually ran.
- **Skipped** counts the records on which the rule did not run. Examples are a judge that reached its [budget](../validation/expectations.md#caching-and-budget), or a rule that its [`row_condition`](../validation/expectations.md#row-conditions) waived. A skipped rule is not a pass and not a fail. Thus it cannot change a rate for records to which it never applied. A rule that never ran shows `—`, not a rate.
- **Records passed** counts `overall_pass`. Only outcomes of `error` severity gate `overall_pass`. A `warn` rule can fail on a record that still passes. That is the purpose of `warn`.
  The heading names each `warn` or `info` rule that failed at least one time. Thus the heading does not look clean when a `warn` rule fails.
  For each rule, the heading gives the failed count over the checked count. The rules with the most failures are first.
  If more than five rules failed, the heading names the first five and gives a count of the others. The rate, `--fail-under` and `--json` do not change:

  ```
  warned  4/4 records passed · 100%  ⚠ 1 non-blocking rule failed: never_matches_warn (warn) 4/4
  ```
- **`⚠ N records carried no verdict`** shows when an action produced output for records that have no verdict. For example, a record that [`on_exhausted: fail`](../validation/expectations.md#the-expect-block) makes into a tombstone keeps its output and loses its verdict.
  Without this line, the remaining records would look fully healthy. A [guard-skipped](../execution/guards.md) record produced no output at all. The report does not count it against the action.

If no record of an action has a verdict, the report says that the action has no verdicts. It does not show zeroes. An action that never ran expectations and an action whose rules all passed are different results.

The report does not run the preflight checks. It reads the results of earlier runs. A configuration that no longer validates is a reason to read the report, not a reason to refuse it. The report also never writes. For a workflow with no store, the report says that there is no store. It does not create a store.

### JSON Output {/* #json-output-1 */}

```bash
agac expect report -a my_workflow --json | jq '.actions[] | {action, pass_rate}'
```

Each action has `records`, `records_passed`, `records_total`, `unverified` and `pass_rate`. Each rule has its `passed` / `failed` / `skipped` counts.

### Gate CI with a Threshold {/* #gating-ci-with-a-threshold */}

Without a threshold, the report only adds annotations. With a threshold, the report is a gate:

```bash
agac expect report -a my_workflow --fail-under 95
```

```
Error: Expectation gate failed for workflow 'my_workflow': pass rate under 95%:
summarize 82% (412/500)
```

The exit code is 0 when each action reaches the threshold. In all other cases, the exit code is non-zero. A rate that is exactly *at* the threshold passes. The option is `fail-under`, not fail-at-or-under.

**The gate rates each action separately.** With an average of all actions, a healthy action would lift a broken action above the threshold. A gate exists to prevent that result.

**Three states fail closed.** The reason is that a gate that reports success when it verified nothing is worse than no gate:

| State | Why it fails |
|-------|--------------|
| The pass rate of an action is under the threshold | This is the condition that you asked about |
| An action whose rules a run would evaluate stored no verdict | Nothing checked the rules. Thus the gate cannot use them |
| An action produced records that have no verdict | If the gate rates only the remaining records of a run, it reports them as fully healthy. A record on which the action ran and failed has no output, as a skipped record has no output. The state of the record shows the difference |

### Actions That the Gate Excludes {/* #what-the-gate-leaves-alone */}

The gate excludes an action when no run could have written a verdict for it. The reason is that no threshold could ever fix that condition:

| Excluded | Why |
|----------|-----|
| `is_operational: false` | To switch an action off is a routine configuration change. It must not make CI impossible to pass |
| A tool or HITL action at file granularity | Its [rules never run](#rules-that-will-not-run) |
| Skipped or filtered for each record that got to it | The action did not run. Thus its missing verdict is not an omission. The `on_false: filter` value of a guard drops the record fully, and the action has no stored row at all. The disposition shows that a run got to the action |

The gate also does not use verdicts that a previous run left for an excluded action. If it did, the only way to pass again would be to delete the store.

If the gate excludes each action that declares rules, there is nothing to gate. The command then exits 0 and says so on stderr. The reason is that an exit code alone looks like "checked and passed". The command fully refuses a scope where no action declares an `expect:` block. In that scope, nothing can ever be checked.

A threshold that is not a real number is a usage error.

The message names the scope that it gated. It starts with the number of actions that nothing checked. When it truncates a list, it gives the count:

```
Error: Expectation gate failed for workflow 'my_workflow': 20 of 30 actions
whose rules a run would evaluate stored no verdict: author, contract, rewrite,
ground, verify_1 and 15 more
```

In CI:

```yaml
- name: Check output quality
  run: agac expect report -a my_workflow --fail-under 95
```

The report still prints (or writes JSON) before the gate fails. Thus the failed run keeps the details in the log.

## See Also {/* #see-also */}

- **[Expectations](../validation/expectations.md)**: How to write the rules that this command lists
- **[inspect Command](./inspect)**: The structure of the workflow and the preflight status

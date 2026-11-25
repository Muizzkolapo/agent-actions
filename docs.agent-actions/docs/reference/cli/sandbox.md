---
title: sandbox Command
description: Run a workflow in the sandbox and check the result against the expected outcomes
sidebar_position: 9
---

# sandbox Command

The `sandbox` commands test a workflow with [sandbox runs](../../guides/sandbox.md). A sandbox run calls no model and needs no API key.

## `sandbox check`

Run a workflow in the sandbox, and compare the result with the expected outcomes in a file:

```bash
agac sandbox check -w my_workflow
```

The command does these steps:

1. It reads and checks the expectations file. A problem stops the command with exit code 2, before the run. An action name that the workflow does not have is found only after the run. See the list of refusals below.
2. It runs the workflow as `agac run -w my_workflow --sandbox --fresh --wait` does, in the same process. The run follows the scenario that a sandbox run reads. See [The scenario file](../../guides/sandbox.md#scenario).
3. It reads the result from the sandbox output before the run releases the run lock: the status of each action, the counts of the sandbox store and the counts of the `SANDBOX scenario` line.
4. It prints one row for each value that the file states, and a `PASS` or `FAIL` line.

```
Sandbox check of support_desk against sandbox_expected.yml:
  ✓ exit code              0
  ✓ scenario errors        8
  ✓ classify status        completed
  ✗ classify filtered      expected 2, got 1
FAIL: 1 of 4 expectations do not hold:
  classify filtered: expected 2, got 1
```

The output of the run comes before the table.

### A Run That Wrote No Result {/* #no-result */}

The check reads only a result that its own run wrote. The run writes the status file of the sandbox output when it loads the workflow. A run can stop before that, for example when the scenario or the workflow configuration does not load, or when another command holds the run lock. The sandbox output then holds the result of an earlier run, and the check does not read it. It compares only `exit_code`, prints a row that does not hold, and fails with exit code 1, whatever the file states:

```
Sandbox check of support_desk against sandbox_expected.yml:
  ✓ exit code  1
  ✗ run        wrote no result (the run stopped with exit code 1)
FAIL: 1 of 2 expectations do not hold:
  run: wrote no result (the run stopped with exit code 1)
```

The error of the run comes before the table.

### Options

| Option | Description |
|--------|-------------|
| `-w`, `--workflow` | The workflow name (required). `-a` names the same option |
| `--expected PATH` | The expectations file. A relative path is from the project root. Default: `sandbox_expected.<workflow>.yml` at the project root, else `sandbox_expected.yml` |
| `--scenario happy\|chaos\|PATH` | The scenario of the run, as for `agac run --sandbox`. A relative path is from the current directory. Default: `sandbox.<workflow>.yml`, else `sandbox.yml`, else `happy` |
| `-u`, `--user-code` | The folder of the tools, as for `agac run` |
| `-e`, `--execution-mode` | `auto` (default), `parallel` or `sequential`, as for `agac run` |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Each value that the file states holds |
| 1 | One or more values do not hold, or the run wrote no result. The `FAIL` line and the rows after it name each value |
| 2 | The expectations file is missing or not valid (see the list of refusals below), or the check could not run: the command ran outside a project, or an unexpected error stopped it. The error is one `Error:` line (`Error: sandbox check could not run: ...` for an unexpected error), and the check prints no table |
| 130 | The check was interrupted (Ctrl-C) |

The exit code of the run is a value of the file (`exit_code`), not the exit code of the command. Thus a file can expect a run that fails: `exit_code: 3` holds when some records fail.

### The Expectations File {/* #expectations-file */}

```yaml
# sandbox_expected.yml
exit_code: 0                 # the exit code of agac run

scenario:                    # the counts of the SANDBOX scenario line
  errors: 8
  rules_broken: 4
  batch_results_dropped: 2

actions:                     # per action: its status and its record counts
  classify: {status: completed, success: 4, filtered: 1}
  billing_team: {success: 2, sent_elsewhere: 2}
  tag_reply: {status: completed, records: 4}
```

The check compares only the values that the file states. Each key is optional, but the file must state one value or more.

| Key | Value |
|-----|-------|
| `exit_code` | The exit code of the run: 0, 1, 3, 4 or 5, as [`agac run`](./run.md) gives it. Another number is refused |
| `scenario.errors`, `scenario.rules_broken`, `scenario.batch_results_dropped` | The three counts of the line `SANDBOX scenario <name>: <n> errors, <m> rules broken, <k> batch results dropped`. With no such line (the run stopped before the mock answered a call), each count is none and does not hold |
| `actions.<action>.status` | The status of the action at the end of the run, as the status file holds it: `pending`, `running`, `batch_submitted`, `checking_batch`, `completed`, `completed_with_failures`, `failed`, `skipped` or `interrupted` |
| `actions.<action>.records` | The records that the action stored, as the `Records` column of [`agac dispositions`](./dispositions.md) |
| `actions.<action>.<count>` | A disposition count of the action, as `agac dispositions --json` gives it: `total`, `sent_elsewhere`, `success`, `failed_checks`, `failed`, `exhausted`, `guard_skipped`, `unprocessed`, `passthrough`, `filtered`, `skipped`, `deferred` |

Name an action as `agac dispositions` names it: each version (`score_1`, `score_2`), each iteration of a loop (`round_iter2__write`), the loop, the router and the join.

The check refuses these entries with exit code 2. The message names the file and the key:

- An unknown key, at the top level, under `scenario` or under an action.
- A count that is not a whole number 0 or more, a status that is not in the list, and an `exit_code` that `agac run` does not give.
- An action entry that states no value, such as `classify:` or `classify: {}`.
- An action that the workflow does not have. The check finds this after the run, in the status file that the run wrote. When the run wrote no result, the check does not read the actions, so it does not refuse a name. The check fails, as [A run that wrote no result](#no-result) says.

The mock and the scenario decide in the same way for the same input, also in a parallel run. Thus a sandbox run gives the same values each time, and a file can state them exactly. See [Each decision is per record](../../guides/sandbox.md#each-decision-is-per-record).

### The Sandbox Output

The run clears and writes only the sandbox output: `agent_io/sandbox/` and `agent_io/store/<workflow>.sandbox.db`. It does not read or change the output of a real run. The output stays after the check, so you can read it with `--sandbox`:

```bash
agac dispositions -w my_workflow --sandbox
agac records -w my_workflow -A classify --sandbox
```

The run holds the run lock of the workflow, as `agac run` does, and the check reads the result before the lock is released. A check and a run of the same workflow cannot run at the same time, and no other run can change the result before the check reads it.

### Examples

```bash
# Check the starter project of agac init --template sandbox
agac sandbox check -w support_desk

# Check the same workflow under the chaos preset, against its own file
agac sandbox check -w support_desk --scenario chaos --expected chaos_expected.yml

# The same check, in sequential mode
agac sandbox check -w support_desk -e sequential
```

## See Also

- [Sandbox runs](../../guides/sandbox.md)
- [`agac init --template sandbox`](./utilities.md#init)
- [`agac dispositions`](./dispositions.md)

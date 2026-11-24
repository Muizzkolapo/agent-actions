---
title: Sandbox Runs
description: Run a workflow end to end offline, with the mock provider and separate output
sidebar_position: 6
---

# Sandbox Runs

`agac run --sandbox` runs a workflow end to end with no model call and no API key. The offline mock provider, `agac-provider`, answers each LLM action. You do not edit the workflow. The output of a sandbox run is kept apart from the output of real runs.

Use a sandbox run to test the connections of a workflow: the dependencies, guards, `context_scope`, versions, routers, loops, batch actions, repair loops and HITL actions. A sandbox run takes seconds and costs nothing. It does not wait for a provider. See [No wait for a provider](#no-wait).

```bash
agac run -w my_workflow --sandbox
```

The run prints `SANDBOX` on stderr when it starts. After its result, it prints a `SANDBOX run` line. At the end of the command, it prints one `SANDBOX scenario` line that counts the faults of the [scenario](#scenario).

## What Changes in a Sandbox Run

Agent Actions loads the workflow as for a real run. Then it changes these actions:

| Action | In a sandbox run |
|--------|------------------|
| LLM action | The mock provider answers it. The action keeps its `model_name`, which the traces and `inspect` show |
| Tool action | Runs its own code, as in a real run |
| HITL action | Approves each record and opens no review UI. The records get `hitl_status: approved` and the comment `auto-approved (sandbox)` |

Preflight checks the changed workflow. A key that is not set is not an error, because the mock reads no key. The configuration must still be valid for its real vendor. For example, an action on a vendor that takes a key must name `api_key`, as for a real run.

A workflow that declares `outputs:` does not write its database tables in a sandbox run. The run also does not check the connections of those tables.

## No Wait for a Provider {/* #no-wait */}

The mock answers immediately, so a sandbox run does not wait where a real run waits for a provider:

| Wait | Real run | Sandbox run |
|------|----------|-------------|
| The backoff before a retry of a rate limit, a network error or a server error, and the time that a provider's `Retry-After` gives | Waits | Does not wait. The event log names the wait that the run did not make: `(backoff 0.42s; skipped in sandbox)` |
| The time between two passes of `agac run --wait`, when you do not give `--poll` | 60 seconds | No wait. See [Batch actions](#batch-actions) |
| The wait before a second try to get the results of a batch | Waits | Does not wait |

A sandbox run waits only where you tell it to wait: the `latency_ms` and `batch.complete_after_seconds` of the [scenario](#scenario), and a `--poll` that you give. The retry limits stay the same: an action with `retry: {max_attempts: 3}` makes three attempts.

## What the Mock Answers

The mock makes each record from the schema of the action. It also reads the expectation rules of the action, so a record usually passes them. See [Testing rules with the mock provider](../reference/validation/expectations.md#testing-rules-with-the-mock-provider) for the rules that the mock meets. An `llm_judge` rule gets a verdict as [Testing a judge offline](../reference/validation/expectations.md#testing-a-judge-offline) tells.

The mock counts the attempts of each record separately. A repair round is the next attempt of its record. In a sandbox run, a retry and a later run continue the count. See [Each decision is per record](#each-decision-is-per-record).

A judge passes by default in a sandbox run. A [scenario](#scenario) can set the pass rate.

## The Scenario File {/* #scenario */}

A scenario makes the mock fail, change or delay some calls on purpose. Use it to test the recovery paths of a workflow: retry, repair, the failure hint and `agac retry`. The scenario comes from one of these sources:

| Command | Scenario |
|---------|----------|
| `agac run -w my_workflow --sandbox` | `sandbox.yml` at the project root. If there is no such file, the `happy` preset |
| `agac run -w my_workflow --sandbox --scenario chaos` | The `happy` or the `chaos` preset |
| `agac run -w my_workflow --sandbox --scenario path/to/faults.yml` | That file |

`agac retry --sandbox` takes `--scenario` too. Without `--sandbox`, `--scenario` is an error. The read commands do not read a scenario.

Agent Actions reads and checks the scenario when it loads the workflow, before it calls the mock. A problem stops the command. The message names the scenario file (`sandbox.yml` or the path you gave) and each key that is wrong.

### Format

```yaml
seed: 42                        # default 0
defaults:                       # every LLM action
  latency_ms: [20, 120]         # a number, or [min, max]; default 0
  judge: {pass_rate: 1.0}
  errors: {rate: 0.0, kinds: [rate_limit], heal_on_attempt: null}
  break_rules: {rules: all, rate: 0.0, heal_on_attempt: null}
actions:
  extract:                      # an LLM action, or the base name of a version group
    break_rules: {rules: [matches_regex], rate: 0.3, heal_on_attempt: 2}
    errors: {rate: 0.05, kinds: [rate_limit, timeout, refusal, truncated, empty]}
  classify:
    pin: {label: urgent}        # a fixed value for a field of the output schema
records:
  - match: {source.page_id: p3} # dotted paths into the input of the record
    actions:
      extract: {error: refusal} # this record fails each attempt with a refusal
batch:
  polls_until_complete: 0       # status checks that report the batch in progress
  complete_after_seconds: 0     # seconds before a status check can complete the batch
  drop_rate: 0.0                # results that a collected batch leaves out
  fail: []                      # actions whose batch fails at the provider
```

| Key | What it does |
|-----|--------------|
| `seed` | Changes every decision. The same seed makes the same decisions |
| `latency_ms` | Online only: the mock waits this time before each answer. A range gives a time in the range. A batch uses the `batch` timing keys |
| `judge.pass_rate` | The probability that a judge answers `passed: true`, online and in a batch |
| `errors` | With the probability `rate`, the call fails with one of `kinds`. See [Error kinds](#error-kinds) |
| `break_rules` | With the probability `rate`, the mock changes the record so that the real check of a rule fails. `rules: all` breaks one error-severity rule of the action. An action with no such rule is not changed. A list of rule types breaks each rule of those types |
| `heal_on_attempt` | The attempt of a record from which a fault stops. With `heal_on_attempt: 2`, the first attempt fails and the next attempt passes: the retry, the repair round or `agac retry`. `null` never stops the fault |
| `pin` | Sets each named field of the record to the value. The field must be in the output schema of the action. The value is kept also when the schema or a rule refuses it. The mock then logs one warning for each action and field |
| `records` | Each entry gives the rules of the records that its `match` selects. `error: <kind>` makes each attempt of the record fail with that kind. An entry can also set `errors`, `break_rules`, `pin` and `latency_ms` |
| `batch` | The timing and the faults of the mock batch provider |

A record entry takes precedence over `actions`, and `actions` takes precedence over `defaults`. Each key replaces the key below it whole. For example, the `errors` of an action replace the `errors` of `defaults`.

A name under `actions`, under `records[].actions` and in `batch.fail` is an LLM action or the base name of a version group. The base name applies to each version (`score` applies to `score_1` and `score_2`). An entry for the exact name of a version takes precedence over an entry for its base name.

`match` reads the whole input of the record: each field that the action observes, also a field that its prompt prints. For example, `match: {source.page_id: p3}` selects the record whose `source.page_id` is `p3`.

The checks refuse these entries:

- An unknown key.
- An action name that is not an LLM action or the base name of a version group.
- An unknown error kind, or an unknown rule type in `break_rules.rules`.
- A rate outside 0 to 1, a `heal_on_attempt` less than 2, or a `latency_ms` range whose minimum is more than its maximum.
- `judge` in a `records` entry. A judge call answers no record, so set `judge` under `actions` or `defaults`.
- A `pin` field that the output schema of the action does not declare.
- `pin` or `break_rules` under `actions` or `records` for an action with no JSON output schema (text mode). The `break_rules` of `defaults` do not apply to such an action.

### Each Decision Is Per Record

The mock makes each decision from the seed, the action, the input of the record, the attempt and the name of the decision. The input of a record is the same in each run, also below an expansion or a FILE tool, where the `source_guid` of a record is new in each run. Thus:

- The order of the calls does not change a decision. A parallel run fails the same records as a sequential run.
- Two `--fresh` runs with the same input and scenario fail the same records.
- Two records with the same input get the same decisions.

The mock counts the attempts of each record at each action, from 1. In a sandbox run the count is kept in the sandbox store, `agent_io/store/<workflow>.sandbox.db`. A retry, a repair round, a later pass of `--wait` and `agac retry --sandbox` are each the next attempt of the record, online and in a batch. In a batch, each submission of a record is its next attempt. Thus `heal_on_attempt` can stop a fault in a retry run.

These events start the count again:

| Event | Count |
|-------|-------|
| `agac run --sandbox --fresh` | Starts again for each action |
| `agac run --sandbox --rerun <action>` | Starts again for that action and the actions that read it |
| An input record is removed from the staged input, and a run sees that | Starts again for that record, at the action that read it and the actions that read that action. If you stage the same input again, it is a new record: its count starts at 1 |
| `agac clean --all` | Removed with the sandbox store |

### Error Kinds {/* #error-kinds */}

Each kind reaches the workflow as the same fault from a real provider does. Thus the real retry and repair paths run.

| Kind | Online, JSON mode | Online, text mode | In a batch |
|------|-------------------|-------------------|------------|
| `rate_limit` | A rate limit error. The retry policy retries it | Same | A failed line with status 429 |
| `timeout` | A network error. The retry policy retries it | Same | A failed line with the error `Request timed out.` |
| `server_error` | A server error (503). The retry policy retries it | Same | A failed line with status 503 |
| `refusal` | A record with the parse error `The model refused to answer` | An error that the retry policy does not retry | A line with a refusal |
| `truncated` | The first half of the answer, with a parse error for the output limit | The first half of the answer, kept as the answer, as a real provider returns it | A line cut off at the output limit |
| `empty` | A record with the parse error `Empty response from API` | An error that the retry policy does not retry | A line with no content |
| `invalid_json` | A record that no parse can read | Text that is not JSON | A line with text that is not JSON |

A record with a parse error fails the schema check, so an `expect:` block with `repair` sends it again as a schema failure. Without an `expect:` block, or with `repair: none`, the record fails. A transport fault (`rate_limit`, `timeout`, `server_error`) is sent again only when the action sets `retry:`. In a batch, the retry batch sends a failed line again.

### Batch Actions in a Scenario

The mock batch provider makes the same decisions for each record when it returns the results. A dropped result is left out only the first time that the record is sent, so the retry batch gets it. An action in `batch.fail` gets a batch that the provider reports as failed.

A batch reports `in_progress` for its first `polls_until_complete` status checks, and until `complete_after_seconds` passed. The first status check after both completes it. With both at 0, which is the default, the first status check completes the batch.

`agac run --sandbox --wait` makes one status check in each pass. Without `--poll`, it does not wait between two passes, so `polls_until_complete` adds passes and no time. When `complete_after_seconds` is more than 0, it waits that time between two passes, at most 1 second. See [Batch actions](#batch-actions).

### Presets

| Preset | Scenario |
|--------|----------|
| `happy` | No faults. The judge passes |
| `chaos` | `seed: 0`. Each LLM action: `errors {rate: 0.1, kinds: [rate_limit, timeout, truncated, empty], heal_on_attempt: 2}`, `break_rules {rules: all, rate: 0.2, heal_on_attempt: 2}` and `judge {pass_rate: 0.7}`. Batch: `polls_until_complete: 1` (the first status check of each batch reports `in_progress`) and `drop_rate: 0.1` |

Each fault of `chaos` stops at the second attempt of its record. A `chaos` run completes when each LLM action has both of these:

- `retry:` with two attempts or more, for the transport faults.
- An `expect:` block with `repair: auto`, for the cut-off and empty answers and the broken rules.

These records fail:

- A record of an action without `retry:`, when its first call gets a transport fault.
- A record of a JSON action without `repair`, when its first answer is cut off or empty.
- A record of a text-mode action (no JSON output schema), when its first answer is empty. A real provider's empty text answer is an error that the retry policy does not retry, and a text answer has no repair. A cut-off text answer is kept as the answer.

The summary line and the failure hint show these records.

### The Summary Line

After the result, a sandbox run or retry prints one line with the counts of the whole command. With `--wait`, the line counts each pass. With `agac retry --all`, the line counts each pass too, and comes after the last pass:

```
SANDBOX scenario chaos: 3 errors, 2 rules broken, 1 batch results dropped
```

When an error stops the command after the mock answered a call, the command prints the line before the error message. The line then counts the faults up to the error. A command that stops before the first call prints no line. A retry that finds no record to retry prints no line.

When you give `--scenario`, the hints that name `agac run` or `agac retry` name the same `--scenario`.

## Separate Output

A sandbox run writes to these locations. A real run does not read them, and a sandbox run does not read or change the output of a real run.

| Output | Real run | Sandbox run |
|--------|----------|-------------|
| Durable store | `agent_io/store/<workflow>.db` | `agent_io/store/<workflow>.sandbox.db` |
| Action status | `agent_io/.agent_status.json` | `agent_io/sandbox/.agent_status.json` |
| Target folder (batch input files) | `agent_io/target/` | `agent_io/sandbox/target/` |
| Event logs and run results | `agent_io/logs/` | `agent_io/sandbox/logs/` |
| Run history | `artefact/runs.json` | `agent_io/sandbox/artefact/runs.json` |

Thus a sandbox run never makes a real action look complete. A real run after a sandbox run answers each action as if the sandbox run did not occur.

The two kinds of run share these items:

- The input: `agent_io/staging/` or the data source of the workflow.
- The run lock, `agent_io/store/<workflow>.db.lock`. A sandbox run and a real run of one workflow cannot run at the same time. The second run stops with `Another run of workflow '<workflow>' is in progress`.
- The local records of the mock batch provider, under `.agac/batch_state/`.
- The rendered workflow file, under `artefact/rendered_workflows/`.

`--fresh` with `--sandbox` clears the sandbox output only.

## Read the Sandbox Output

Give `--sandbox` to a command to read the sandbox output in place of the real output:

```bash
agac status -w my_workflow --sandbox
agac records -w my_workflow -A summarize --sandbox
agac traces -w my_workflow -A summarize --sandbox
agac dispositions -w my_workflow --sandbox
agac preview -w my_workflow --sandbox
agac usage -w my_workflow --sandbox
agac expect report -w my_workflow --sandbox
```

`agac retry --sandbox` retries the failed records of a sandbox run, with the mock. It reads and writes only the sandbox output.

`agac inspect --sandbox` shows the workflow as a sandbox run runs it. The action detail marks each LLM action `answered by the sandbox mock`:

```bash
agac inspect -w my_workflow --sandbox action summarize
```

## Batch Actions {/* #batch-actions */}

An action with `run_mode: batch` goes to the mock batch provider. A batch run pauses after it submits, as with a real provider. Run the workflow again with `--sandbox`, or give `--wait`:

```bash
agac run -w my_workflow --sandbox --wait
```

In a sandbox run, `--wait` does not wait between two passes when you do not give `--poll`. It prints `Checking the batch job(s) again...` and runs the next pass immediately. A real run waits 60 seconds.

A scenario can hold each batch for a time (`batch.complete_after_seconds`). Then `--wait` waits that time between two passes, at most 1 second, and prints the time: `Waiting 1s before checking the batch job(s) again...`. A `--poll` that you give is used as given, also in a sandbox run.

## Remove the Sandbox Output

`agac clean --all` removes the sandbox output together with the real output: `agent_io/sandbox/` and the sandbox store. It also reclaims the local records of the batches that the sandbox store names, as it does for the real store. `agac clean --target` removes only `agent_io/target/`. See [clean](../reference/cli/utilities.md#clean).

The `reset_workflow.py --full` script of the skills removes the sandbox output too.

## Limits

- The records are generated. They test the connections of the workflow, not the prompts or the quality of the answers.
- A rule that the mock cannot meet still fails, for example an `expression` rule or a custom check that the generated values do not pass. The mock logs a warning for each such field.
- A rule that `break_rules` cannot break, for example an `llm_judge` rule or a rule type that the action does not check, stays as it is. The mock logs one warning for each action and rule.
- `agac usage --sandbox` counts the calls of the mock under the model `agac-mock`, with zero tokens.
- `agac export` has no `--sandbox` option.

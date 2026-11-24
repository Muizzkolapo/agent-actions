---
title: Sandbox Runs
description: Run a workflow end to end offline, with the mock provider and separate output
sidebar_position: 6
---

# Sandbox Runs

`agac run --sandbox` runs a workflow end to end with no model call and no API key. The offline mock provider, `agac-provider`, answers each LLM action. You do not edit the workflow. The output of a sandbox run is kept apart from the output of real runs.

Use a sandbox run to test the connections of a workflow: the dependencies, guards, `context_scope`, versions, routers, loops, batch actions, repair loops and HITL actions. A sandbox run takes seconds and costs nothing.

```bash
agac run -w my_workflow --sandbox
```

The run prints `SANDBOX` on stderr when it starts. After its result, it prints a `SANDBOX scenario` line that counts the faults of the [scenario](#scenario), and a `SANDBOX run` line.

## What Changes in a Sandbox Run

Agent Actions loads the workflow as for a real run. Then it changes these actions:

| Action | In a sandbox run |
|--------|------------------|
| LLM action | The mock provider answers it. The action keeps its `model_name`, which the traces and `inspect` show |
| Tool action | Runs its own code, as in a real run |
| HITL action | Approves each record and opens no review UI. The records get `hitl_status: approved` and the comment `auto-approved (sandbox)` |

Preflight checks the changed workflow. A key that is not set is not an error, because the mock reads no key. The configuration must still be valid for its real vendor. For example, an action on a vendor that takes a key must name `api_key`, as for a real run.

A workflow that declares `outputs:` does not write its database tables in a sandbox run. The run also does not check the connections of those tables.

## What the Mock Answers

The mock makes each record from the schema of the action. It also reads the expectation rules of the action, so a record usually passes them. See [Testing rules with the mock provider](../reference/validation/expectations.md#testing-rules-with-the-mock-provider) for the rules that the mock meets. An `llm_judge` rule gets a verdict as [Testing a judge offline](../reference/validation/expectations.md#testing-a-judge-offline) tells.

The mock counts the attempts of each record separately. A repair round is the next attempt of its record. Each run, a retry included, starts each record at the first attempt.

A judge passes by default in a sandbox run. A [scenario](#scenario) can set the pass rate.

## The Scenario File {/* #scenario */}

A scenario makes the mock fail, change or delay some calls on purpose. Use it to test the recovery paths of a workflow: retry, repair, the failure hint and `agac retry`. The scenario comes from one of these sources:

| Command | Scenario |
|---------|----------|
| `agac run -w my_workflow --sandbox` | `sandbox.yml` at the project root. If there is no such file, the `happy` preset |
| `agac run -w my_workflow --sandbox --scenario chaos` | The `happy` or the `chaos` preset |
| `agac run -w my_workflow --sandbox --scenario path/to/faults.yml` | That file |

`agac retry --sandbox` takes `--scenario` too. Without `--sandbox`, `--scenario` is an error. The read commands do not read a scenario.

Agent Actions reads and checks the scenario when it loads the workflow, before it calls the mock. A problem stops the command, and the message names the file and each key that is wrong.

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
    pin: {label: urgent}        # a fixed value for a field
records:
  - match: {source.page_id: p3} # dotted paths into the context of the request
    actions:
      extract: {error: refusal} # this record fails each attempt with a refusal
batch:
  polls_until_complete: 0       # status checks before a batch completes
  complete_after_seconds: 0     # seconds before a batch completes
  drop_rate: 0.0                # results that a collected batch leaves out
  fail: []                      # actions whose batch fails at the provider
```

| Key | What it does |
|-----|--------------|
| `seed` | Changes every decision. The same seed makes the same decisions |
| `latency_ms` | The mock waits this time before each answer. A range gives a time in the range |
| `judge.pass_rate` | The probability that a judge answers `passed: true` |
| `errors` | With the probability `rate`, the call fails with one of `kinds`. See [Error kinds](#error-kinds) |
| `break_rules` | With the probability `rate`, the mock changes the record so that the real check of a rule fails. `rules: all` breaks one rule of the action. A list of rule types breaks each rule of those types |
| `heal_on_attempt` | The attempt of a record from which a fault stops. With `heal_on_attempt: 2`, the first attempt fails and the retry or the repair round passes. `null` never stops the fault |
| `pin` | Sets each named field of the record to the value. The value is kept also when the schema or a rule refuses it. The mock then logs one warning for each action and field |
| `records` | Each entry gives the rules of the records that its `match` selects. `error: <kind>` makes each attempt of the record fail with that kind. An entry can also set `errors`, `break_rules`, `pin`, `judge` and `latency_ms` |
| `batch` | The timing and the faults of the mock batch provider |

A record entry takes precedence over `actions`, and `actions` takes precedence over `defaults`. Each key replaces the key below it whole. For example, the `errors` of an action replace the `errors` of `defaults`.

The checks refuse an unknown key, an action name that names no LLM action of the workflow, an unknown error kind, an unknown rule type in `break_rules.rules`, a rate outside 0 to 1, a `heal_on_attempt` less than 2, and a `latency_ms` range whose minimum is more than its maximum.

### Each Decision Is Per Record

The mock makes each decision from the seed, the action, the record, the attempt and the name of the decision. The record is its `source_guid`, which each run gives the same record. Thus the order of the calls does not change a decision: a parallel run fails the same records as a sequential run. The same scenario fails the same records in each run.

The attempts of each record start at 1 in each run. A retry and a repair round are the next attempt of the record. In a batch, each submission of a record for an action is its next attempt, also when a later run submits it.

### Error Kinds {/* #error-kinds */}

Each kind reaches the workflow as the same fault from a real provider does. Thus the real retry and repair paths run.

| Kind | Online, JSON mode | Online, text mode | In a batch |
|------|-------------------|-------------------|------------|
| `rate_limit` | A rate limit error. The retry policy retries it | Same | A failed line with status 429 |
| `timeout` | A network error. The retry policy retries it | Same | A failed line with the error `Request timed out.` |
| `server_error` | A server error (503). The retry policy retries it | Same | A failed line with status 503 |
| `refusal` | A record with the parse error `The model refused to answer` | An error that the retry policy does not retry | A line with a refusal |
| `truncated` | The first half of the answer, with a parse error for the output limit | A truncation error. The retry policy retries it | A line cut off at the output limit |
| `empty` | A record with the parse error `Empty response from API` | An error that the retry policy does not retry | A line with no content |
| `invalid_json` | A record that no parse can read | Text that is not JSON | A line with text that is not JSON |

A record with a parse error fails the schema check, so an `expect:` block sends it again as a schema failure. Without an `expect:` block, the record fails. In a batch, the retry batch sends a failed line again.

### Batch Actions in a Scenario

The mock batch provider makes the same decisions for each record when it returns the results. A dropped result is left out only the first time that the record is sent, so the retry batch gets it. An action in `batch.fail` gets a batch that the provider reports as failed.

Without a scenario that sets the timing, a mock batch completes at the first status check.

### Presets

| Preset | Scenario |
|--------|----------|
| `happy` | No faults. The judge passes |
| `chaos` | `seed: 0`. Each LLM action: `errors {rate: 0.1, kinds: [rate_limit, timeout, truncated, empty], heal_on_attempt: 2}`, `break_rules {rules: all, rate: 0.2, heal_on_attempt: 2}` and `judge {pass_rate: 0.7}`. Batch: `polls_until_complete: 1` and `drop_rate: 0.1` |

Each fault of `chaos` stops at the second attempt of its record. Thus a workflow whose actions have `retry:` (two attempts or more) and an `expect:` block with `repair: auto` completes. A workflow without them shows which actions do not recover.

### The Summary Line

After its result, a sandbox run or retry prints one line with the counts of this run:

```
SANDBOX scenario chaos: 3 errors, 2 rules broken, 1 batch results dropped
```

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
- The local records of the mock batch provider, under `.agac/batch_state/`, and its count of the submissions of each record, `.agac/batch_attempts.json`.
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

## Batch Actions

An action with `run_mode: batch` goes to the mock batch provider. A batch run pauses after it submits, as with a real provider. Run the workflow again with `--sandbox`, or give `--wait`:

```bash
agac run -w my_workflow --sandbox --wait --poll 1
```

## Remove the Sandbox Output

`agac clean --all` removes the sandbox output together with the real output: `agent_io/sandbox/` and the sandbox store. It also reclaims the local records of the batches that the sandbox store names, as it does for the real store. `agac clean --target` removes only `agent_io/target/`. See [clean](../reference/cli/utilities.md#clean).

The `reset_workflow.py --full` script of the skills removes the sandbox output too.

## Limits

- The records are generated. They test the connections of the workflow, not the prompts or the quality of the answers.
- A rule that the mock cannot meet still fails, for example an `expression` rule or a custom check that the generated values do not pass. The mock logs a warning for each such field.
- A rule that `break_rules` cannot break, for example an `llm_judge` rule or a rule type that the action does not check, stays as it is. The mock logs one warning for each action and rule.
- `agac usage --sandbox` counts the calls of the mock under the model `agac-mock`, with zero tokens.
- `agac export` has no `--sandbox` option.

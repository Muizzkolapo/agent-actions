# Sandbox testing

`agac run --sandbox` runs a workflow end to end with no model call, no API key and no
cost. The offline mock `agac-provider` answers each LLM action in seconds. You do not edit
the workflow. A sandbox run never mixes its output with the output of a real run.

Full reference, with the table of each scenario key: `docs.agent-actions/docs/guides/sandbox.md`.

## When to use it

Use a sandbox run to test the wiring of a workflow before you pay for a real model:
the DAG, guards, `context_scope`, versions, loops, routers, batch actions, retry, repair
and HITL actions. Run it again after each change to the workflow.

A sandbox run does not test the prompts or the quality of the answers. The mock answers
with generated values.

## Commands

All commands run from the project root.

```bash
agac run -w {workflow} -u tools --sandbox                       # sandbox.yml, else the happy preset
agac run -w {workflow} -u tools --sandbox --fresh               # clear the sandbox output first
agac run -w {workflow} -u tools --sandbox --scenario chaos      # a preset, or a file path
agac run -w {workflow} -u tools --sandbox --wait                # batch actions: run every pass
agac retry -w {workflow} --sandbox                              # retry the failed sandbox records
agac inspect -w {workflow} -u tools --sandbox action {action}   # the action as the sandbox runs it
```

## What is mocked and what is real

| Part | In a sandbox run |
|------|------------------|
| LLM action | The mock answers. The answer meets the schema and the deterministic `expect:` rules. An output field copies the upstream field of the same name when observe names that field exactly (not with a wildcard; under `context_block: auto`, not a field the prompt prints). The same input gets the same answer in each run |
| `llm_judge` rule | The judge passes, unless the scenario sets `judge.pass_rate` |
| Tool action | Runs its own code. A tool that the scenario stubs does not run: the mock builds its output from its schema |
| HITL action | Approves each record. No review UI opens |
| Guards, context scope, dispositions, store | Real |
| Output | `agent_io/sandbox/` and `agent_io/store/{workflow}.sandbox.db` |
| Run lock | Shared with real runs. A sandbox run and a real run of one workflow cannot run at the same time |

A sandbox run does not wait for backoff, `Retry-After` or batch polls. A workflow with
`outputs:` writes no database table in a sandbox run.

## The scenario file

A scenario makes the mock fail, change or delay calls on purpose. Put it in `sandbox.yml`
at the project root, or give `--scenario <path>` to `run`, `retry` or `inspect`. A real run
does not read it. Each decision is per record and repeats run to run.

```yaml
seed: 7                                   # another seed makes other decisions
defaults:                                 # every LLM action
  errors: {rate: 0.1, kinds: [rate_limit, timeout], heal_on_attempt: 2}
actions:
  extract:
    break_rules: {rules: [matches_regex], rate: 1.0, heal_on_attempt: 2}
    latency_ms: [20, 120]                 # online only
  score:                                  # the base name of a version group
    judge: {pass_rate: 0.5}
  classify:
    pin: {label: urgent}                  # a fixed value for a schema field
  search_catalog:                         # a tool action that calls a service
    stub: true                            # its code does not run
records:
  - match: {source.page_id: p3}           # a dotted path into the record's input
    actions:
      extract: {error: refusal}           # this record fails each attempt
batch:
  polls_until_complete: 1                 # status checks that report in progress
  drop_rate: 0.1                          # results left out of the first batch
  fail: [summarize]                       # actions whose batch fails
```

- `errors` kinds: `rate_limit`, `timeout`, `server_error`, `refusal`, `truncated`, `empty`,
  `invalid_json`.
- `heal_on_attempt: 2` fails the first attempt of a record and passes the next one: the
  retry, the repair round or `agac retry --sandbox`. `null` never heals.
- The sandbox store counts the attempts of each record, so `agac retry --sandbox` continues
  the count. `--fresh` starts the count again.
- A tool action takes only `stub` and `pin`, and `pin` only with `stub: true`.
- A `records` entry replaces `actions`, and `actions` replaces `defaults`, key by key.
- An action in a loop has one name for each iteration. Give one entry for each
  iteration (`round_iter1__check`, `round_iter2__check`, ...). The bare name `check` is
  refused, and the refusal lists the valid names.
- A change to the scenario does not run a completed action again. Use `--fresh` or
  `--rerun <action>`.
- The run reads and checks the scenario before the first call. A wrong key stops the command
  and names the file and the key. `agac inspect -w {workflow} --sandbox` checks it with no run.

## Presets

| Preset | What it does |
|--------|--------------|
| `happy` | No faults. The judge passes. The default when there is no `sandbox.yml` |
| `chaos` | Transport errors, cut-off and empty answers, broken rules, judge pass rate 0.7, a delayed batch and dropped batch results. Each fault heals on the second attempt |

`chaos` completes only when each LLM action has `retry:` with two attempts or more and an
`expect:` block with `repair: auto`. A preset stubs no tool and does not read `sandbox.yml`.
To combine faults with stubs, write the faults and the `stub` entries in one scenario file.

## Read the results

1. The run prints `SANDBOX` lines on stderr when it starts, and on stdout after its result.
   The last one counts the faults:
   `SANDBOX scenario chaos: 3 errors, 2 rules broken, 1 batch results dropped`.
2. The exit codes are those of a real run: 0 every action succeeded, 1 the run failed,
   3 some records failed, 4 paused for a batch.
3. Give `--sandbox` to the read commands: `agac status`, `agac records`, `agac traces`,
   `agac dispositions`, `agac preview`, `agac usage`, `agac expect report`.
4. `agac usage --sandbox` shows the model `agac-mock` with zero tokens.

## Testing recipes

| To test | Do this |
|---------|---------|
| A guard filters what it should | `pin` the field that the guard reads. Pin a failing value for one record with `records[].match`. Count with `agac dispositions -w {workflow} --sandbox` |
| Repair heals a broken rule | `break_rules: {rules: [<type>], rate: 1.0, heal_on_attempt: 2}` on the action. The summary counts the broken rules, and the action completes |
| `on_exhausted` and the failure path | The same `break_rules` with `heal_on_attempt: null` |
| `agac retry` | `errors: {rate: 1.0, kinds: [server_error], heal_on_attempt: N}`, with N one more than `retry.max_attempts`. The run exits 1 or 3. Then `agac retry -w {workflow} --sandbox --scenario <file>` heals the records |
| The paths after a judge | `judge: {pass_rate: 0.5}` on the action |
| A network tool, offline | `stub: true` on the tool action. The line of the tool shows `(stubbed)` after the time, then its notes, for example `(stubbed) — 1 skipped by guard` |
| One record path | `records[].match` on an input field, with `pin` or `error` for that record |
| Batch recovery | `run_mode: batch`, then `batch.drop_rate` or `batch.fail`, and `agac run --sandbox --wait` |

## Limits

- The data is fake. A sandbox run checks wiring, not prompt quality or real model behaviour.
- An `empty` fault on a text-mode action (no JSON output schema) does not recover. The retry
  policy does not retry it, and text has no repair.
- A FILE tool cannot be stubbed. A RECORD tool that returns a list gives one record when stubbed.
- A stubbed tool gives the same output to two records whose observed input is the same. The
  mock seeds the output with the action name and the observed input of the record.
- A tool that is not stubbed runs its code. If the code calls a service, the sandbox run calls it.
- The mock cannot meet every rule (for example an `expression` rule). It logs a warning.
- A sandbox run says nothing about cost, quota or real latency.
- `scripts/reset_workflow.py {workflow} --full` removes the sandbox output, together with the
  real output.

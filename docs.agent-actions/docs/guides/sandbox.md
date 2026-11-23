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

The run prints `SANDBOX` on stderr when it starts. It prints a `SANDBOX run` line on stdout after its result.

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

The mock counts the attempts of each record separately. A repair round is the next attempt of its record.

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

`agac clean --all` removes the sandbox output together with the real output: `agent_io/sandbox/` and the sandbox store. `agac clean --target` removes only `agent_io/target/`. See [clean](../reference/cli/utilities.md#clean).

## Limits

- The records are generated. They test the connections of the workflow, not the prompts or the quality of the answers.
- A rule that the mock cannot meet still fails, for example an `expression` rule or a custom check that the generated values do not pass. The mock logs a warning for each such field.
- `agac usage --sandbox` counts the calls of the mock under the model `agac-mock`, with zero tokens.
- `agac export` has no `--sandbox` option.

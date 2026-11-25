---
name: agac-operations
description: Run large agent-actions workflows safely and find a run that ends with no error but with bad output. Triggers on batch or online mode, run_mode, resume after a crash, --rerun, retry --all, --wait, exit codes, agac usage, agac dispositions --json, cost, memory, context window limits, oversized inputs, a sandbox rehearsal, or "the run succeeded but the output is wrong or too small".
---

# Agent Actions Operations

Run large agent-actions workflows safely, and find a run that ends with no error but with bad output.

Use this skill when a workflow runs over many records (hundreds to many thousands), runs for hours, or costs real money. The `agac-agent-skills` skill tells you how to build a workflow. This skill tells you how to run it, recover it and check it.

**Paths:** `scripts/*.py` are relative to this skill's directory. Run them from the project root (where `agent_actions.yml` is).

## Terms

| Term | Meaning in this skill |
|---|---|
| step | One level of the run plan. A step holds one action, or more than one action that run at the same time |
| record | One unit of input data that moves through the actions |
| output | What an action wrote for a record |
| usable output | An output that the next action can use: not empty, not failed, not a placeholder |

## Rules

1. **Check the output, not only the exit code.** A run can end with exit code 0 and keep a small part of its records. Every part of the run can do what its config allows: an `llm_judge` votes FAIL, the repair rounds are used up, `on_exhausted: return_last` keeps the last output, and the next guard filters the record. Run `scripts/run_health.py` after each pass (see [Health check](#health-check)).
2. **Test the run mode that the full run uses.** Run a small sample in batch mode before a full batch run. Do not assume that an online test predicts a batch run.
3. **Never edit the staging input of a workflow that can resume.** A changed or new staging file changes the plan. Use `--fresh` for new input, or add new input as a new file. A `database` data source reads its query once into a snapshot; to pick up new rows, use `--refresh-input`, which answers only the rows that are new or changed.
4. **Never change the agent-actions code that a live run imports.** A run started from an editable install reads the code at each import.
5. **Keep paid output.** To change one action, use `agac run -w <workflow> --rerun <action>`. It runs that action and every action that reads it again on every record. The other actions keep their output. To change only some records, add `--where '<guard expression>'` or `--records ids.txt`: the records that do not match keep their answers at every action, and `--dry-run` shows the count first. `--fresh` throws away all output.
6. **Rehearse a large run offline first.** Run `agac run -w <workflow> -u tools --sandbox --scenario chaos --wait` before you pay. It tests retry, repair and recovery with no model call (see [Rehearse offline](#rehearse-offline)).

## Commands

All commands run from the project root. `-u tools` is needed when the workflow has tools. `-w` names the workflow and `-A` names an action in every command.

```bash
agac run -w <workflow> -u tools                    # run, or resume from the last finished action
agac run -w <workflow> -u tools --wait             # wait for open batches, then exit with the final code
agac run -w <workflow> -u tools --rerun <action>   # run <action> and its readers again; keep the rest
agac run -w <workflow> -u tools --rerun <action> --where '<guard expression>'   # only the matching records; --dry-run counts them first
agac run -w <workflow> -u tools --rerun <action> --records ids.txt             # only the listed source_guids
agac retry -w <workflow> --all                     # retry from the earliest failure until no pass helps
agac retry -w <workflow> --filter <action>:<record_id> --reason "<why>"   # stop retrying one record
agac run -w <workflow> -u tools --refresh-input    # read a database source's query again (refused while a batch is open)
agac export -w <workflow>                          # write the workflow's `outputs:` tables again, no model calls
agac dispositions -w <workflow> --json             # counts per action, for scripts
agac status -w <workflow> --json                   # status of each action and of the run
agac usage -w <workflow>                           # model calls and tokens per action
agac run -w <workflow> -u tools --sandbox --scenario chaos --wait   # offline rehearsal with faults
agac retry -w <workflow> --sandbox --all           # retry the failed records of sandbox runs
```

Exit codes of `agac run` and `agac retry`:

| Code | Meaning |
|---|---|
| 0 | The run finished. Every action succeeded |
| 1 | The run failed |
| 3 | The run finished, but some records failed |
| 4 | The run paused for a batch (or `--wait-timeout` passed). Run again later |
| 5 | A provider quota or credit stopped the run |

See run (docs: `reference/cli/run`), retry (docs: `reference/cli/retry`), dispositions (docs: `reference/cli/dispositions`) and usage (docs: `reference/cli/usage`).

## Batch or online

`run_mode: batch` sends one provider batch per action and file, at about half the online price. The run pauses (exit code 4) until the batch ends. `run_mode: online` calls the model record by record.

| Choose batch when | Choose online when |
|---|---|
| The run is large and can wait hours | You need the output in minutes |
| Cost matters more than time | You test a prompt on 2 or 3 records |
| The action makes one call per record | An action has few records left (a repair round of 3 records waits a full batch cycle) |

You can set `run_mode` in `defaults:` and override it on one action. `llm_judge` calls follow the action's mode, or `expect: {judge_mode: batch | online}`. See Run modes (docs: `reference/execution/run-modes`) and Batch recovery (docs: `reference/execution/batch-recovery`).

The batch and online paths read an answer, call the judge and check the context window in the same way. Before a large batch run, run your sample in batch mode once, and compare it with an online run of the same records.

## Resume and recovery

agent-actions stores each finished action in `agent_io/store/<workflow>.db` and the status of each action in `agent_io/.agent_status.json`. After a crash, a reboot or a stop, run the same `agac run` command again. Finished actions stay finished.

To recover from a bad action without paying again for the actions before it, read [references/recovery.md](references/recovery.md). It shows the "recovery tool action + `--rerun`" pattern.

## Health check

`scripts/run_health.py` reads `agac dispositions --json` and `.agent_status.json`. It stops your loop when an action keeps far less usable output than normal.

```bash
python3 scripts/run_health.py -w <workflow>                    # default limits
python3 scripts/run_health.py -w <workflow> --max-bad 0.2 --min-records 20
python3 scripts/run_health.py -w <workflow> --sandbox          # the output of sandbox runs
```

1. For each action, it counts `success` against `failed`, `failed_checks` and `exhausted`.
2. It reports an action whose bad share is above `--max-bad` (default 0.2), when the action has at least `--min-records` checked records (default 20).
3. It exits 1 when an action is above the limit, 0 when none is, and 2 when it cannot read the counts.
4. It checks only actions that `.agent_status.json` marks `completed` or `completed_with_failures`. An action that `--rerun` reset is not finished, and its counts can still show the old run until it runs again.

Put it in your run loop after each `agac run` and `agac retry`:

```bash
agac run -w my_workflow -u tools --wait; code=$?
python3 .claude/skills/agac-operations/scripts/run_health.py -w my_workflow || exit 1
```

Calibrate `--max-bad` on a good run of your own workflow. Some actions fail many records on purpose (a strict filter), so set the limit per workflow, not from this file.

The health check reads counts. It does not read the content of the output. For a content rate (for example, the share of outputs with at least one extracted line item), add a small tool action that counts it, and guard or check on that count.

## Rehearse offline

`agac run --sandbox` runs the workflow with the offline mock `agac-provider` in place of each LLM action. It needs no API key, costs nothing and takes seconds. Its output goes to `agent_io/sandbox/` and `agent_io/store/<workflow>.sandbox.db`, never mixed with real runs. Give `--sandbox` to `retry`, `status`, `records`, `traces`, `dispositions` and `usage` to act on it. A sandbox run and a real run of one workflow share the run lock.

```bash
agac run -w <workflow> -u tools --sandbox --scenario chaos --wait
python3 scripts/run_health.py -w <workflow> --sandbox --min-records 1
```

1. The `chaos` preset sends transport errors, cut-off and empty answers, broken rules and dropped batch results. Each fault heals on the second attempt of its record.
2. A `chaos` run completes only when each LLM action has `retry:` with two attempts or more and `expect:` with `repair: auto`. A record that fails shows a gap in your retry or repair settings.
3. The run prints one line that counts the faults, for example `SANDBOX scenario chaos: 3 errors, 2 rules broken, 1 batch results dropped`. The exit codes are those of a real run.
4. A preset keeps the tool stubs of the project: the `stub` entries (with their `pin`) of `sandbox.<workflow>.yml`, else `sandbox.yml`, and nothing else of that file. A tool that the project does not stub runs its own code. If a tool calls a service, put `stub: true` on it in the project file. A scenario file given as `--scenario <file>` is used alone, so put the `stub` entries in it.
5. To rehearse one recovery, script the faults in a scenario file. See [references/recovery.md](references/recovery.md), section 5.

A sandbox run says nothing about cost, quota, real latency or the quality of the answers. Its data is fake. Test those on a small real sample (Rule 2). The `agac-agent-skills` skill has the full scenario format in `references/sandbox-testing.md`.

## Scale limits

| Limit | What happens | What to do |
|---|---|---|
| Context window | agent-actions estimates a prompt as characters / 4 and refuses a prompt above the model's window. A model name that it does not know gets 128,000 tokens. `context_window` on the action or in `defaults:` sets the window | Set `context_window` when the model reads more than agent-actions knows. Split oversized inputs (below). Keep large fields out of `observe` where a distilled field exists. Keep `context_block: auto` (the default), so a field the prompt prints is not sent twice |
| Memory | Batch preparation holds the records of the action in memory. Very large records times many records can fill the machine | Close other large programs. Watch the process memory during the first large batch step |
| Disk | The store grows with each action. Old workflow stores and virtual environments add up | Remove old stores with `agac clean --all` or `scripts/reset_workflow.py --full` (agac-agent-skills) when you no longer need them |
| Rate limits | Online mode with high `record_concurrency` gets HTTP 429 from some providers | Set `retry` and `request_timeout` in `defaults:`. Lower `record_concurrency` for providers with low limits |

See Context handling (docs: `reference/execution/context-handling`) and Chunking (docs: `reference/data-io/chunking`).

### Splitting an oversized input

For a JSON, CSV, TSV or Excel record with one very long top-level field, set `chunk_config: {field: source.<name>}` on the first action or in the workflow's `defaults:`. Each part becomes a record of its own, with every other field and `chunk_index` and `chunk_count`. It uses the same `chunk_size`, `chunk_overlap` and `split_method` as text files.

For a record that `field` cannot split (the long text is nested, or spread over many fields):

1. Split it before staging, into parts with a unique key each (for example, `url#part-2`). Two records with the same key collide.
2. Put the parts in a new staging file, so the existing files do not change (Rule 3).
3. Mark the original record filtered, so retries stop: `agac retry -w <workflow> --filter <action>:<record_id> --reason "input larger than the context window"`.

## Reading what happened

| To find | Command |
|---|---|
| How many records of each action succeeded or failed? | `agac dispositions -w <workflow> --json` |
| Which records failed, and why? | `agac dispositions -w <workflow> --quarantined` |
| What did one action output? | `agac records -w <workflow> -A <action>` |
| What prompt did the model get? | `agac traces -w <workflow> -A <action>` |
| What did the run cost in tokens? | `agac usage -w <workflow>` |

Do not read the store tables directly. Their payload columns are compressed, and their layout can change between releases. Use the commands above.

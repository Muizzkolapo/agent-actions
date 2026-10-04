# Workflow Module Architecture

This document maps the moving parts of `agent_actions/workflow/` — the module that orchestrates action execution, manages state, handles batch lifecycles, and coordinates the processing pipeline.

---

## High-Level Overview

```
agac run -a my_workflow
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  CLI (cli/run.py)                                        │
│    → load YAML, render templates, build AgentWorkflow    │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│  AgentWorkflow.__init__ (coordinator.py)                 │
│    1. load_workflow_configs → YAML → action configs       │
│    2. initialize_storage_backend → SQLite                 │
│    3. initialize_services → executor, runner, managers    │
│    4. _reset_retryable_actions or _clear_for_fresh_run    │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│  _run_workflow_with_context (coordinator.py)              │
│    Compute levels (topological sort)                     │
│    For each level:                                       │
│      For each pending action:                            │
│        → ActionExecutor.execute_action_sync()            │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│  ActionExecutor (executor.py)                            │
│    1. Config change detection → invalidate completed     │
│    2. Circuit breaker → skip if upstream failed           │
│    3. Skip evaluator → WHERE clause check                │
│    4. _execute_action_run → ActionRunner.run_action()    │
│    5. _resolve_completion_status → COMPLETED / FAILED    │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│  ActionRunner (runner.py)                                │
│    Initial stage → staging pipeline (input preprocessing)│
│    Standard stage → ProcessingPipeline                   │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│  ProcessingPipeline (pipeline.py)                        │
│    Batch mode → submit to provider API, return           │
│    Online mode → UnifiedProcessor.process()              │
│                  (see processing/ARCHITECTURE.md)        │
└──────────────────────────────────────────────────────────┘
```

---

## Action Status Lifecycle

Every action has a status that controls what happens on the current run and on re-runs.

```
                     ┌─────────────────────────────────────────────┐
                     │          On re-run (no --fresh)             │
                     │     _reset_retryable_actions()              │
                     │  RETRYABLE_STATUSES → PENDING               │
                     │  except a FAILED action halted by           │
                     │  on_exhausted: raise — see below            │
                     └──────────┬──────────────────────────────────┘
                                │
    ┌───────────────────────────┼───────────────────────────────────┐
    │                           │                                   │
    ▼                           ▼                                   ▼
┌─────────┐  start action  ┌──────────┐  batch detected   ┌───────────────────┐
│ PENDING │───────────────►│ RUNNING  │──────────────────►│ BATCH_SUBMITTED   │
└─────────┘                └──────────┘                    └───────────────────┘
    ▲                         │  │  │                          │
    │ reset_retryable()       │  │  │                     poll │
    │                         │  │  │                          ▼
    │          ┌──────────────┘  │  └───────────┐        ┌──────────────┐
    │          ▼                 ▼               ▼        │CHECKING_BATCH│
    │    ┌──────────┐  ┌─────────────────┐  ┌─────────┐  └──────┬───────┘
    ├────│  FAILED  │  │  COMPLETED_WITH │  │ SKIPPED │         │
    │    └──────────┘  │    _FAILURES    │  └─────────┘         │
    │                  └─────────────────┘       ▲              │
    │                        │                   │              │
    │                        │ (in COMPLETED_    │              │
    │                        │  STATUSES — NOT   ├──────────────┘
    │                        │  retryable)       │
    │                   ┌────┴─────┐             │
    └───────────────────│COMPLETED │─────────────┘
       (only via config └──────────┘
        change or         (survives re-run)
        missing output)
```

One transition sits outside the diagram because it is driven by the process
dying rather than by the workflow: on Ctrl-C, SIGTERM or cancellation the
coordinator sweeps `RUNNING`/`CHECKING_BATCH` to `INTERRUPTED` on its way out.
It is terminal and retryable, so the next run resets it to `PENDING` like any
other retryable status — but it is deliberately not `FAILED`: in a status file written
before an action's start recorded its config, the status is all the reset can go by, and
it keeps the checkpointed dispositions of an interrupted action but not of a failed one.

### Status Sets

```
COMPLETED_STATUSES = {COMPLETED, COMPLETED_WITH_FAILURES}
  → "Has valid output, skip on re-run"
  → Used by: is_completed(), coordinator level skip, executor early-exit

TERMINAL_STATUSES = {COMPLETED, FAILED, SKIPPED, COMPLETED_WITH_FAILURES,
                     INTERRUPTED}
  → "Done for this run, regardless of outcome"
  → Used by: is_workflow_complete(), is_workflow_done(), get_pending_actions()

RETRYABLE_STATUSES = {FAILED, SKIPPED, RUNNING, CHECKING_BATCH, INTERRUPTED}
  → "Reset to PENDING on next run"
  → COMPLETED_WITH_FAILURES is NOT retryable (spec 534, 2026-05-31)

MID_PROCESSING_STATUSES = {RUNNING, INTERRUPTED, CHECKING_BATCH}
  → "Died mid-processing; may hold checkpointed SUCCESS dispositions"
  → Used by: _reset_retryable_actions, which with FAILED takes them as stopped
    partway, and keeps what one finished while its config is unchanged
```

### Completion Classification

`executor.py:_resolve_completion_status()` — called after every action run
that returned. An action whose run raised is FAILED without reaching this
classifier, so FAILED there does not imply zero successes:

```
get_failed_items() returns failures?
    │
    NO → COMPLETED
    │
    YES → has_successful_items()?
           │
           YES → COMPLETED_WITH_FAILURES
           NO  → FAILED (zero successes = hard failure)
```

---

## The Execution Loop

### Sequential Mode

```
coordinator.py:_run_workflow_with_context()

for each level in topological order:
    │
    ├── verify_completion_status() for completed actions
    │   (guards against stale DB — resets if output missing)
    │
    ├── filter to pending actions only
    │
    └── for each pending action:
          _run_single_action(action_name)
              │
              ├── ActionExecutor.execute_action_sync()
              │
              └── returns True → STOP (batch submitted)
                  returns False → continue
```

`_run_single_action` returns True ONLY for `BATCH_SUBMITTED`. Even `FAILED` returns False — the circuit breaker in the next level handles cascade.

### Parallel Mode

```
parallel/action_executor.py:execute_level_async()

for each level:
    │
    ├── verify completed actions
    │
    ├── get pending actions
    │
    ├── 1 pending → execute_single_action (no semaphore)
    │   N pending → asyncio.gather(*tasks) with Semaphore
    │               (each task runs in asyncio.to_thread)
    │
    └── check for BATCH_SUBMITTED → pause if found
```

Important: `asyncio.to_thread` wraps synchronous `run_action()`. Parallel execution is thread-based, not coroutine-based. True I/O overlap is between different actions only; within a single action, processing is synchronous.

---

## ActionExecutor — Decision Tree

Every action goes through this decision tree before any code runs:

```
execute_action_sync(action_name)
    │
    ▼
Config changed since last run?
(prompt, model, schema, guard changed)
    YES → invalidate COMPLETED, reset to PENDING
          and reset every action that reads its output, in any state,
          directly or through other actions (see below)
    │
    ▼
Already COMPLETED?
    YES → verify output exists
          output missing → reset to PENDING, and what reads it likewise
          output present → skip, return success
    │
    ▼
BATCH_SUBMITTED?
    YES → _handle_batch_check() → poll provider
    │
    ▼
Upstream dependency FAILED or SKIPPED?
    YES → _handle_dependency_skip()
          set SKIPPED; if a dependency or version source holds no rows,
          forget its dispositions, checkpoints and batch state and delete
          its stored rows (not under a repair of named records); write
          node-level DISPOSITION_SKIPPED
          (cascade — all downstream will also skip)
    │
    ▼
WHERE clause says skip?
    YES → _handle_action_skip()
          set COMPLETED (not SKIPPED — additive model)
    │
    ▼
_execute_action_run()
    → set RUNNING
    → ActionRunner.run_action()
        walk found no input file (not under a repair)?
        YES → NoInputFilesError → _handle_no_input()
              set SKIPPED, forget and delete its stored rows,
              write node-level DISPOSITION_SKIPPED
              (its readers skip under it, holding nothing)
    → _resolve_completion_status()
```

**A reset reaches everything that reads it.** A completed action put back to pending
because its config, model or limit changed, or because its output is gone, is about to
answer everything again. Whatever an action that reads that output holds was computed
from what is being replaced: the answers of a completed one, the batch of one still out,
the records an interrupted or halted one had finished. Left as it is, it ends holding
answers for records that are gone and none for the new ones, while the workflow reports
success. Each reader is reset with it, whatever state it was left in: dispositions,
checkpoint records and batch state are cleared, and a batch still out is given up and
named in a warning, since it was sent the old output. A reader is an action that depends
on it, merges its versions, or only names it in its context scope or prompt, and the
reader of a reader.

The stores are cleared first, readers and then the action (its own are left where only
its output is gone), and the statuses are written last, all in one write (`ActionStateManager.reopen`). A process that dies before that
write leaves every status as it was and the reason for the reset still readable, so the
next run does all of it again; one that dies after it leaves all of them pending. It is
done when the action is reset and not as each reader is reached, because a batch action
pauses the run and the next process no longer knows which action was reset.

An action stopped partway is reset the same way when its config differs from the one its
run recorded as it started, at the start of the next run (`_reset_retryable_actions`); see
"A stopped action keeps what it finished while its config is unchanged".

Two routes run a completed action again and leave its readers alone: a node-level
failure it recorded, and output that could not be read. There the action still holds its
rows and its records' dispositions, so it answers only what failed and carries the rest,
and what its readers computed from those rows stands. A row it adds on that run does not
reach a reader that has completed (#1229).

A run that is repairing records (`agac retry` with records to re-run) acts on no
comparison and resets no reader. It answers only the records it named, so a reset under it clears
every other record's disposition with nothing run to replace them. It warns when it
meets an edited action, one it is about to re-run included, and it keeps the completion stamp it found on each action it
completes, so the next plain run still finds the edit and applies it. A retry with no
record to re-run (only a node-level failure) is a plain run for this purpose.

A repair narrows only what finished its last run. It carries what an action holds for
the records it does not name, and an action never run since it was put back to pending,
or stopped partway through its records, holds no answer for the ones that run had not
reached: narrowed, it completes without them and nothing runs it again. So `agac retry`
refuses, before it clears anything, when an action from its starting point is pending,
running, interrupted, stopped while collecting, or failed by anything but reaching all of
its input, and says to run the workflow first. A failure that reached all of its input
(`EVERY_INPUT_FAILED`) holds a failure for every record and is what a repair is for. Not
refused either: what an interrupted retry put back to pending, which had finished before
that retry and is resumed by retrying again, and a halt, which a plain run will not resume.

Costs and limits:

- A prompt change at the top of a long workflow re-answers everything below it.
- A limit counts as a change. `--record-limit` on a run resets the actions whose records
  it can reach and their readers, giving up a batch still out below and clearing a halt.
- A reset does not delete stored rows; the re-run replaces them as it writes each file.
  The exception is a re-run that finds no input file at all: it is skipped and its rows
  are deleted. One whose input lost some files but not all keeps the rows of the files
  that are gone, and its readers run on them. A re-run that is interrupted and resumed can
  serve the old row for a record it had already answered again (#1226).
- A retry still narrows a halted action when it names a record that failed elsewhere,
  and completes it without the records past the halt. And a retry clears the checkpoint
  records of every action it re-runs, so one that resumes a halt after an edit carries,
  for a record the halted run had answered, the row stored before the edit.
- The level loop orders by `dependencies` alone. A reader that names an action only in
  its context scope and sits in an earlier level is reset after its level has passed, and
  runs on the next run (#1228).


---

## Config Pipeline: YAML → Action Configs

```
agent_config/{workflow}.yml
    │
    ▼
ConfigRenderingService.render_and_load_config()
    → Jinja2 template rendering (env vars, includes)
    → yaml.safe_load()
    │
    ▼
ConfigManager.load_configs()
    │
    ├── get_user_agents()
    │     └── ActionExpander.expand_actions_to_agents()
    │           ├── Loop expansion: versions: {range: [1,2,3]}
    │           │   → creates action_1, action_2, action_3
    │           ├── Guard normalization
    │           ├── Schema compilation
    │           └── Tool/HITL kind detection
    │
    ├── merge_agent_configs()
    │     └── Each action merged onto DefaultAgentConfig
    │         Priority: action > workflow defaults > project defaults
    │
    └── determine_execution_order()
          ├── Normalize context_scope field references
          ├── Infer dependencies from field references
          ├── Build dependency graph
          └── Topological sort → execution_order
```

### Defaults Merging Priority

```
1. Action-level config (from YAML actions: section)
2. Workflow-level defaults (from YAML defaults: section)
3. Project-level defaults (from agent_actions.yml default_agent_config)
4. Framework defaults (from DefaultAgentConfig / SIMPLE_CONFIG_FIELDS)
```

Simple fields: direct override. `chunk_config`: deep merge. `context_scope`: deep merge with defaults.

---

## ProcessingPipeline — The Fork Point

`pipeline.py:_process_by_strategy()` is where online and batch paths diverge:

```
_process_by_strategy(data, file_path, ...)
    │
    ├── Load source_data from SQLite (if available)
    ├── Apply record_limit
    ├── Build shared pipeline context
    │
    ▼
run_mode == BATCH and not tool/HITL?
    │
    YES → _handle_batch_generation()
    │       ├── BatchTaskPreparator.prepare_tasks()
    │       ├── BatchSubmissionService.submit_batch_job()
    │       └── Write placeholder JSON + registry
    │
    NO → Build ProcessingContext
         ├── target_relative_path = the name save_main_output stores the file under
         ├── _select_strategy()
         │     ├── FILE + tool → FileToolStrategy
         │     ├── FILE + HITL → HITLStrategy
         │     └── else → OnlineLLMStrategy
         │
         ├── FILE mode:
         │     apply_context_scope_for_records() → filtered + skipped
         │     raw_records = data minus the positions skipped named
         │     UnifiedProcessor.process(filtered, raw_records=raw_records)
         │       (the two must stay paired position-for-position —
         │        prefilter_by_guard refuses a length mismatch)
         │
         └── RECORD mode:
               UnifiedProcessor.process(data)
         │
         ▼
    stats.raise_if_terminal_failure()
    output_handler.save_main_output()
    write_dispositions(context.kept_dispositions)   ← only after the file
    clear_checkpoint_records(action, target_relative_path)
```

---

## Batch Lifecycle

```
Run 1: Submit
  _handle_batch_generation()
    → submit_batch_job() → provider API (OpenAI/Anthropic batch)
    → write .batch_registry.json
    → DISPOSITION_DEFERRED for all records
    → action status → BATCH_SUBMITTED
    → workflow pauses

Run 2: Poll
  _handle_batch_check()
    → CHECKING_BATCH
    → BatchLifecycleManager.handle_batch_agent()
        │
        ├── get_registry_status()
        │     reads .batch_registry.json
        │
        ├── "completed" → process_all_batch_results()
        │     → skip each entry already collected (collected_at): its
        │       results are written, and a later run may have written
        │       the file again since
        │     → retrieve results from provider
        │     → reconcile (expected - received = missing)
        │     → recovery state machine (retry → repair → finalize)
        │     → write output + dispositions
        │
        ├── "in_progress" → poll provider APIs
        │     all done? → process
        │     not done? → return "in_progress" → BATCH_SUBMITTED again
        │
        └── "failed"/"cancelled" → return error

Run N: Resume (if recovery submitted)
  Same poll path — recovery batches are registered in .batch_registry.json
  with recovery_type and parent_file_name. Processed like original batches.
```

---

## Service Initialization Order

`initialize_services()` creates objects in strict dependency order:

```
1. ActionRunner          ← DI container, tool discovery
2. BatchClientResolver   ← resolves provider SDK by vendor name
3. BatchContextManager   ← context map persistence
4. BatchJobManager       ← registry manager factory
5. BatchProcessingService← orchestrates result processing
6. VersionOutputCorrelator← version/loop input correlation
7. ActionStateManager    ← .agent_status.json persistence
8. SkipEvaluator         ← WHERE clause evaluation
9. BatchLifecycleManager ← polling + processing lifecycle
10. ActionOutputManager   ← previous output loading
11. ActionExecutor        ← bundles all above + console
12. ActionLevelOrchestrator ← topological sort + parallel dispatch
13. ManifestManager       ← .manifest.json for external tools
```

---

## State Persistence

| What | Where | Format | Written when |
|------|-------|--------|-------------|
| Action status | `agent_io/.agent_status.json` | JSON dict | Every `update_status()` call |
| Record dispositions | `agent_io/store/{name}.db` | SQLite table | At checkpoint and collection; online, SUCCESS and PASSTHROUGH after the file |
| Checkpoint records | `agent_io/store/{name}.db` | SQLite table | Per-record during invocation |
| Target output | `agent_io/store/{name}.db` + `agent_io/target/` | SQLite + JSON file | After `save_main_output` |
| Batch registry | `agent_io/target/{action}/batch/.batch_registry.json` | JSON | After batch submit |
| Recovery state | `agent_io/target/{action}/batch/.recovery_state_{file}.json` | JSON | Between retry/repair rounds |
| Prompt traces | `agent_io/store/{name}.db` | SQLite table | During collection |

---

## Invariants and Caveats — What Breaks If You Change Things

### Initialization order is load-bearing

```
Storage backend MUST initialize before services.
    Why: 6 of the 14 services take storage_backend as a constructor arg.
    If you defer storage init, those services get None → silent no-ops
    or NoneType crashes at runtime.

_reset_retryable_actions MUST run after services init, before execution.
    Why: it queries ActionStateManager (needs status file loaded) and
    calls storage_backend.clear_disposition (needs DB connection).
    If you move it before services init → AttributeError on state_manager.

A read-only load MUST skip it entirely (AgentWorkflow(read_only=True)).
    Why: dispositions, schema and retry only inspect persisted state.
    Resetting first destroys the rows they read — retry queries the
    disposition table after construction, so it finds nothing to retry.
```

### A deliberate halt is not a retryable failure

An action that failed because an `on_exhausted: raise` policy fired is marked
with `HALTED_ON_EXHAUSTED` in its node-level disposition's `detail`, set from
the policy every exhaustion site attaches to the exception it raises (see
`errors.exhaustion_halt`). The failure
is deterministic, so re-running it costs the same and ends the same way.

Two mechanisms keep it halted, because either alone is insufficient:

- `_reset_retryable_actions` excludes marked actions, so the status and the
  dispositions survive as evidence.
- `execute_action` refuses to run one. The status alone gates nothing: there is
  no FAILED branch, and the sequential run loop selects on `not is_completed`.
  (The parallel loop selects on `get_pending_actions`, which already excludes
  every terminal status, so there the exclusion alone would do.)

`agac retry` clears the node-level disposition, and `--fresh` clears everything,
so both remain working resume paths.

The same `detail` marks a failure that reached all of the action's input with
`EVERY_INPUT_FAILED`: every record failed (`_finalize_total_failure`), or every
input file failed on its own, none to an error fatal to the action
(`mark_every_file_failed`). Any other failure may have stopped the action partway,
and a failure recorded before the marker existed reads as one.

### COMPLETED_WITH_FAILURES is NOT retryable

```
COMPLETED_WITH_FAILURES was removed from RETRYABLE_STATUSES in spec 534.

If you add it back:
    On re-run, the workflow rewinds to earlier partially-failed actions
    instead of finishing the current run. A 10-action workflow interrupted
    at action 9 goes back to action 3 (which had 2 failures out of 10)
    and reprocesses all 10 records.

The retry command is the dedicated path for fixing partial failures.
It clears only the failed records' dispositions, preserving successes.
```

### A stopped action keeps what it finished while its config is unchanged

```
When the executor starts an action's work it records, in the write that
sets RUNNING, what that work is answered under: `answered_under`, holding
the config hash, model_name and model_vendor. The status changes after it
(FAILED, INTERRUPTED, BATCH_SUBMITTED, CHECKING_BATCH, a sweep) leave it.

_reset_retryable_actions takes an action stopped partway and compares
that with the config in force, as the executor compares a completed one.
Stopped partway is one of:
    RUNNING        — the process died without unwinding (SIGKILL, OOM,
                     power loss), so nothing rewrote the status.
    INTERRUPTED    — the coordinator caught Ctrl-C/SIGTERM/cancellation
                     and recorded a terminal status on the way out.
    CHECKING_BATCH — the process died while collecting a batch. The
                     files it reached are written and their records done.
    FAILED         — an error stopped it, running or collecting; one that
                     raised may hold successes. Not one halted by
                     `on_exhausted: raise`, which is not reset at all.

    unchanged → clear only RUNNING_CLEAR_DISPOSITIONS
                (FAILED, EXHAUSTED, DEFERRED); SUCCESS, PASSTHROUGH,
                FILTERED, SKIPPED and the prompt traces stay, and the
                DispositionGate carries them. Online writes SUCCESS
                and PASSTHROUGH after the file holding the record's
                row is stored; one answered since holds a checkpoint
                row instead (processing/ARCHITECTURE.md, "Checkpoint
                and Resume")
    edited    → ActionExecutor.reopen_with_readers: it and every action
                reading it are forgotten (dispositions, checkpoints, batch
                state, a batch still out given up) and put back to pending;
                the reset then clears the prompt traces of each
    unknown   → state written before the stamp existed: reset by status,
                selective for MID_PROCESSING_STATUSES, bulk for FAILED

A repair (`agac retry`) records what the records it does not name were
answered under, not the config it runs under: the completion stamp it
keeps, or, for an action that never completed, the `answered_under` its
last run recorded (_held_to_earlier_answers). It stamps the same when it
completes the action. A retry of an edited action, stopped or finished,
leaves the edit to the next run, which applies it to every record.

If you clear a stopped action in bulk while its config is unchanged:
    Checkpoint resume breaks — the DispositionGate finds no terminal IDs
    and reprocesses everything from scratch. For a batch that means
    submitting, and paying for, every collected file again.

If you keep what it finished after an edit:
    The gate carries answers given under the old prompt or model, the
    batch jobs still out are collected as they are, and the action is then
    stamped complete under the new config, so nothing re-runs it.
```

### The reset decides before it writes a status

```
for each stopped action:  edited → reopen_with_readers (one status write)
                          else   → keeps.add(name)
reset_actions = state_mgr.reset_retryable(exclude=halted)  ← mutates to PENDING

Both MUST happen before reset_retryable(). It moves every retryable
status to PENDING, after which nothing says which actions were stopped
partway. And an edited action reset after it would sit PENDING, which
is not retryable: a process that died in between would leave it to run
on with what it holds. Before it, the stamp still differs and the next
run repeats the reset.
```

### Config hash invalidation scope

```
_compute_action_config_hash() covers:
    prompt, schema, guard clause, guard behavior
    (model_name and model_vendor are compared from the stamp beside it)

If you change one of these fields and re-run WITHOUT --fresh:
    The executor detects the hash mismatch, resets the action to PENDING,
    and clears its dispositions, and does the same to every action that
    reads it. They re-run with new config. Not while `agac retry` is
    re-running records: it acts on no mismatch and keeps the stamps it
    found, so the next plain run still sees the mismatch. An action stopped
    partway is compared at the start of the next run, against the
    `answered_under` its run recorded (_edits_since serves both).

If you add a new config field that affects output but don't add it
to the hash computation:
    Stale output from a prior config is silently reused. The user
    must manually --fresh to get updated results.
```

### _run_single_action stop semantics

```
_run_single_action returns True ONLY for BATCH_SUBMITTED.

FAILED returns False — the loop continues to the next action.
The circuit breaker (upstream health check) handles cascade.

If you add a new status that returns True:
    The sequential loop stops at that action. All remaining actions
    in the current level AND all subsequent levels are skipped.
    Use this only for conditions that genuinely require pausing
    the entire workflow (like batch polling).
```

### Parallel execution uses threads, not coroutines

```
_execute_action_run_async wraps synchronous run_action in
asyncio.to_thread(). This means:

  - Parallel execution = thread-based (GIL applies to CPU work)
  - True overlap only for I/O between different actions
  - Within a single action, processing is fully synchronous
  - The threading.Lock in ActionStateManager protects status writes

If you add async I/O inside run_action (e.g., aiohttp calls):
    It won't benefit from the event loop — it's running in a
    thread, not a coroutine. You'd need to restructure the entire
    execution path to use native async.
```

### Every path that resets actions must clear checkpoint records

```
Four places reset action state. ALL FOUR clear checkpoint_output:

1. pipeline.py          — after save_main_output (normal completion)
2. coordinator.py       — _clear_for_fresh_run (--fresh flag)
3. cli/retry.py         — RetryCommand.execute (retry command)
4. executor.py          — _forget_what_it_did (an action reset because it or
                          what it reads is running again)

If you add a new CLI command or reset path:
    You MUST call storage_backend.clear_checkpoint_records(action_name).
    If you forget, stale checkpoint data from a prior run silently
    contaminates the next run's output.
```

### WHERE skip produces COMPLETED, not SKIPPED

```
SkipEvaluator.should_skip_action() → True results in:
    _handle_action_skip() → status = COMPLETED

NOT SKIPPED. This is intentional — the additive content model means
a WHERE-skipped action simply adds nothing to the record. It's not
a failure or cascade trigger.

If you change this to SKIPPED:
    All downstream actions that depend on this action will cascade-skip
    via the circuit breaker, even though there's nothing wrong.
```

---

## File Map

| File | Purpose |
|------|---------|
| `coordinator.py` | `AgentWorkflow` — init, run, async_run, reset logic |
| `executor.py` | `ActionExecutor` — full action lifecycle, circuit breaker, batch check |
| `pipeline.py` | `ProcessingPipeline` — online/batch fork, strategy selection |
| `runner.py` | `ActionRunner` — strategy dispatch, directory resolution |
| `runner_file_processing.py` | File walking, storage-first loading, merge-branch processing |
| `strategies.py` | `InitialStrategy`, `StandardStrategy` — runner-level strategies |
| `config_pipeline.py` | `load_workflow_configs` — YAML parsing, UDF discovery |
| `service_init.py` | `initialize_storage_backend`, `initialize_services` |
| `models.py` | All workflow dataclasses (`WorkflowRuntimeConfig`, etc.) |
| `execution_events.py` | `WorkflowEventLogger` — telemetry events |
| `schema_service.py` | Schema compilation and validation |
| `managers/state.py` | `ActionStateManager` — status persistence, status sets |
| `managers/batch.py` | `BatchLifecycleManager` — polling, result processing |
| `managers/output.py` | `ActionOutputManager` — previous output, version correlation |
| `managers/skip.py` | `SkipEvaluator` — WHERE clause, guard |
| `managers/manifest.py` | `ManifestManager` — .manifest.json for external tools |
| `parallel/action_executor.py` | `ActionLevelOrchestrator` — topological sort, parallel dispatch |

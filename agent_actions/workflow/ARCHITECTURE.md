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

### Status Sets

```
COMPLETED_STATUSES = {COMPLETED, COMPLETED_WITH_FAILURES}
  → "Has valid output, skip on re-run"
  → Used by: is_completed(), coordinator level skip, executor early-exit

TERMINAL_STATUSES = {COMPLETED, FAILED, SKIPPED, COMPLETED_WITH_FAILURES}
  → "Done for this run, regardless of outcome"
  → Used by: is_workflow_complete(), is_workflow_done(), get_pending_actions()

RETRYABLE_STATUSES = {FAILED, SKIPPED, RUNNING, CHECKING_BATCH}
  → "Reset to PENDING on next run"
  → COMPLETED_WITH_FAILURES is NOT retryable (spec 534, 2026-05-31)
```

### Completion Classification

`executor.py:_resolve_completion_status()` — called after every action run:

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
    │
    ▼
Already COMPLETED?
    YES → verify output exists
          output missing → reset to PENDING
          output present → skip, return success
    │
    ▼
BATCH_SUBMITTED?
    YES → _handle_batch_check() → poll provider
    │
    ▼
Upstream dependency FAILED or SKIPPED?
    YES → _handle_dependency_skip()
          set SKIPPED, write node-level DISPOSITION_SKIPPED
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
    → _resolve_completion_status()
```

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
         ├── _select_strategy()
         │     ├── FILE + tool → FileToolStrategy
         │     ├── FILE + HITL → HITLStrategy
         │     └── else → OnlineLLMStrategy
         │
         ├── FILE mode:
         │     apply_context_scope_for_records()
         │     UnifiedProcessor.process(filtered, raw_records=data)
         │
         └── RECORD mode:
               UnifiedProcessor.process(data)
         │
         ▼
    stats.raise_if_terminal_failure()
    output_handler.save_main_output()
    clear_checkpoint_records()
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
        │     → retrieve results from provider
        │     → reconcile (expected - received = missing)
        │     → recovery state machine (retry → reprompt → finalize)
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
4. BatchSourceHandler    ← source data for retry
5. BatchJobManager       ← registry manager factory
6. BatchProcessingService← orchestrates result processing
7. VersionOutputCorrelator← version/loop input correlation
8. ActionStateManager    ← .agent_status.json persistence
9. SkipEvaluator         ← WHERE clause evaluation
10. BatchLifecycleManager ← polling + processing lifecycle
11. ActionOutputManager   ← previous output loading
12. ActionExecutor        ← bundles all above + console
13. ActionLevelOrchestrator ← topological sort + parallel dispatch
14. ManifestManager       ← .manifest.json for external tools
```

---

## State Persistence

| What | Where | Format | Written when |
|------|-------|--------|-------------|
| Action status | `agent_io/.agent_status.json` | JSON dict | Every `update_status()` call |
| Record dispositions | `agent_io/store/{name}.db` | SQLite table | After collection or checkpoint |
| Checkpoint records | `agent_io/store/{name}.db` | SQLite table | Per-record during invocation |
| Target output | `agent_io/store/{name}.db` + `agent_io/target/` | SQLite + JSON file | After `save_main_output` |
| Batch registry | `agent_io/target/{action}/batch/.batch_registry.json` | JSON | After batch submit |
| Recovery state | `agent_io/target/{action}/batch/.recovery_state_{file}.json` | JSON | Between retry/reprompt rounds |
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
```

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

### RUNNING actions get selective disposition clearing

```
_reset_retryable_actions clears RUNNING_CLEAR_DISPOSITIONS
(FAILED, EXHAUSTED, DEFERRED) for previously-RUNNING actions.

It does NOT clear SUCCESS, PASSTHROUGH, FILTERED, SKIPPED.

Why: RUNNING actions may have checkpointed SUCCESS dispositions.
Bulk-wiping them destroys resume progress.

If you change this to bulk-clear for RUNNING:
    Checkpoint resume breaks — the DispositionGate finds no terminal
    IDs and reprocesses everything from scratch.
```

### The snapshot ordering in _reset_retryable_actions matters

```
running_actions = {... get_status == RUNNING ...}   ← snapshot BEFORE
reset_actions = state_mgr.reset_retryable()          ← mutates to PENDING

The snapshot MUST be captured before reset_retryable() because
reset_retryable() transitions all matching statuses to PENDING.
After the call, you can't tell which actions were RUNNING.

If you swap the order:
    running_actions is always empty → all actions get bulk-cleared
    → checkpoint resume breaks.
```

### Config hash invalidation scope

```
_compute_action_config_hash() covers:
    prompt, model_name, model_vendor, schema, guard clause, guard behavior

If you change one of these fields and re-run WITHOUT --fresh:
    The executor detects the hash mismatch, resets the action to PENDING,
    and clears its dispositions. The action re-runs with new config.

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
Three places reset action state. ALL THREE clear checkpoint_output:

1. pipeline.py:591      — after save_main_output (normal completion)
2. coordinator.py:285   — _clear_for_fresh_run (--fresh flag)
3. cli/retry.py:201     — RetryCommand.execute (retry command)

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
| `managers/skip.py` | `SkipEvaluator` — WHERE clause, guard, legacy skip_if |
| `managers/manifest.py` | `ManifestManager` — .manifest.json for external tools |
| `parallel/action_executor.py` | `ActionLevelOrchestrator` — topological sort, parallel dispatch |

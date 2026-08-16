# Processing Module Architecture

This document maps the moving parts of `agent_actions/processing/` — the module that takes raw records, runs them through LLM/tool/HITL strategies, and produces enriched output with dispositions.

---

## High-Level Overview

```
                    agent_actions/processing/
                           │
         ┌─────────────────┼─────────────────────┐
         │                 │                      │
     strategies/       invocation/            recovery/
   (what to do)     (how to call it)     (retry + reprompt)
         │                 │                      │
         └────────┬────────┘                      │
                  │                               │
            unified.py                            │
        (the pipeline skeleton)                   │
                  │                               │
         ┌───────┼───────┐                        │
         │       │       │                        │
    enrichment  result   disposition              │
    .py     _collector   _gate                    │
              .py        .py                      │
                                           evaluation/
                                         (batch reprompt
                                          validation)
```

The module has **five concerns**:

| Concern | Where | What it does |
|---------|-------|-------------|
| Pipeline skeleton | `unified.py` | Guard → cascade → invoke → enrich → collect |
| Strategies | `strategies/` | Per-record LLM, file-level tool, file-level HITL |
| Invocation | `invocation/` | Online (sync + retry/reprompt) vs batch (deferred queue) |
| Recovery | `recovery/` | RetryService (transport errors), RepromptService (validation) |
| Post-processing | `enrichment.py`, `result_collector.py`, `disposition_gate.py` | Lineage, metadata, dispositions, carry-forward |

---

## The Record Lifecycle

A record enters `UnifiedProcessor.process()` and exits as an enriched output dict with a disposition in SQLite.

```
Input records (from staging or upstream action)
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  Step 1: GUARD FILTER                                │
│  unified.py:108-115                                  │
│                                                      │
│  Evaluates guard clause from YAML config:            │
│    guard: { condition: '...', on_false: "filter" }   │
│                                                      │
│  Results:                                            │
│    passing    → continue to step 2                   │
│    skipped    → ProcessingResult.skipped() tombstone  │
│    filtered   → ProcessingResult.filtered() (dropped) │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  Step 2: SOURCE_GUID ASSIGNMENT (first-stage only)   │
│  unified.py:121-126                                  │
│                                                      │
│  First-stage records have no source_guid (they come  │
│  from staging files). Assigns deterministic UUID5    │
│  content hash so DispositionGate can match across    │
│  runs for checkpoint resume.                         │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  Step 3: DISPOSITION GATE                            │
│  disposition_gate.py:67-107                          │
│                                                      │
│  Queries SQLite for terminal dispositions (SUCCESS,  │
│  FILTERED, SKIPPED, PASSTHROUGH, EXHAUSTED).         │
│                                                      │
│  Records with terminal disposition → carry forward   │
│    (read prior output from target_data or checkpoint │
│     table, skip reprocessing)                        │
│  Records without → continue to step 4               │
│                                                      │
│  FAILED is NOT terminal — failed records reprocess.  │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  Step 4: CASCADE FILTER                              │
│  cascade_filter.py:25-84                             │
│                                                      │
│  Checks record._state against CASCADE_BLOCKING_VALUES│
│  (cascade_skipped, failed, exhausted)                │
│                                                      │
│  Blocked records → ProcessingResult.unprocessed()    │
│  (downstream can't process what upstream failed on)  │
│  Processable records → continue to step 5            │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  Step 5: STRATEGY INVOCATION                         │
│  strategy.invoke(processable, context)               │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │  OnlineLLMStrategy (per-record)                 │ │
│  │  strategies/online_llm.py:134                   │ │
│  │                                                 │ │
│  │  for each record:                               │ │
│  │    1. TaskPreparer.prepare()                    │ │
│  │       → resolve context, render prompt,         │ │
│  │         evaluate per-record guard               │ │
│  │    2. InvocationStrategy.invoke(prepared)       │ │
│  │       → OnlineStrategy: LLM call + retry/       │ │
│  │         reprompt wrappers                       │ │
│  │       → BatchStrategy: queue for deferred API   │ │
│  │    3. _checkpoint_record()                      │ │
│  │       → write disposition + output to SQLite    │ │
│  │         immediately (resume on interrupt)       │ │
│  │    4. Transform response → output records       │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │  FileToolStrategy (whole-file)                  │ │
│  │  strategies/file_tool.py:29                     │ │
│  │                                                 │ │
│  │  1. Strip framework fields (TrackedItem)        │ │
│  │  2. Call UDF tool with full record array        │ │
│  │  3. reconcile_outputs() — match by source_index │ │
│  │  4. Build tombstones for missing records        │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │  HITLStrategy (whole-file)                      │ │
│  │  strategies/hitl.py:25                          │ │
│  │                                                 │ │
│  │  1. Call HITL agent with filtered records       │ │
│  │  2. Receive single decision payload             │ │
│  │  3. Broadcast decision to all records           │ │
│  │  4. Non-decision status (timeout/error) → raise │ │
│  └─────────────────────────────────────────────────┘ │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  Step 6: ENRICHMENT                                  │
│  enrichment.py:289-369                               │
│                                                      │
│  6 enrichers applied sequentially to each result:    │
│                                                      │
│  1. LineageEnricher     → node_id, target_id,        │
│                           parent lineage             │
│  2. MetadataEnricher    → extracted metadata from     │
│                           LLM response               │
│  3. VersionIdEnricher   → version_correlation_id     │
│  4. PassthroughEnricher → merge passthrough fields   │
│                           into content namespace     │
│  5. RequiredFieldsEnricher → source_guid, target_id  │
│  6. RecoveryEnricher    → _recovery metadata         │
│                           (retry/reprompt details)   │
│                                                      │
│  Carry-forward records bypass enrichment (already    │
│  have correct lineage from prior run).               │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  Step 7: COLLECTION                                  │
│  result_collector.py:324-748                         │
│                                                      │
│  For each ProcessingResult:                          │
│    - Stamp _state on output records                  │
│    - Accumulate disposition rows                     │
│    - Build tombstones for FAILED (online)            │
│    - Fire telemetry events                           │
│                                                      │
│  Flush all dispositions in single SQLite transaction │
│                                                      │
│  Status → Disposition mapping:                       │
│    SUCCESS    → DISPOSITION_SUCCESS                  │
│    SKIPPED    → DISPOSITION_PASSTHROUGH              │
│    FILTERED   → DISPOSITION_FILTERED                 │
│    FAILED     → DISPOSITION_FAILED                   │
│    EXHAUSTED  → DISPOSITION_EXHAUSTED                │
│    UNPROCESSED→ DISPOSITION_UNPROCESSED              │
│    DEFERRED   → DISPOSITION_DEFERRED                 │
│                                                      │
│  Returns: (output_records, CollectionStats)           │
└──────────────────────────────────────────────────────┘
```

---

## Invocation Layer Detail

The invocation layer sits between the strategy and the LLM call.

```
OnlineLLMStrategy.process_record()
    │
    ├── TaskPreparer.prepare()
    │     ├── _normalize_input() → source_guid, snapshot
    │     ├── _load_full_context() → context data for LLM
    │     ├── _evaluate_guard() → per-record guard check
    │     └── _render_prompt() → formatted prompt string
    │
    └── InvocationStrategy.invoke(prepared_task)
          │
          ├── OnlineStrategy (online mode)
          │     │
          │     ├── retry only:     RetryService.execute(llm_call)
          │     ├── reprompt only:  RepromptService.execute(llm_call)
          │     ├── both:           reprompt(retry(llm_call))
          │     └── neither:        direct llm_call
          │
          └── BatchStrategy (batch mode)
                └── queue task, return InvocationResult.queued()
```

### Retry (transport-layer recovery)

```
RetryService.execute(operation)     recovery/retry.py:108
    │
    for attempt in 1..max_attempts:
    │   try:
    │       response = operation()  → success, return
    │   except NetworkError, RateLimitError:
    │       sleep(exponential backoff + jitter)
    │       continue
    │   except non-retriable:
    │       re-raise immediately
    │
    └── all attempts failed → RetryResult(exhausted=True)
```

### Reprompt (validation-layer recovery)

```
RepromptService.execute(llm_operation, original_prompt)
    │                                         recovery/reprompt.py:179
    for attempt in 1..max_attempts:
    │   response = llm_operation(current_prompt)
    │   │
    │   ├── JSON parse error?
    │   │     → build parse-error feedback, retry
    │   │
    │   ├── Schema validation fail? (if on_schema_mismatch: reprompt)
    │   │     → build schema feedback, retry
    │   │
    │   ├── UDF validation fail? (if validation: fn_name)
    │   │     → build UDF feedback, retry
    │   │
    │   ├── LLM critique? (if use_self_reflection and attempt ≥ threshold)
    │   │     → append critique to feedback
    │   │
    │   └── All pass → RepromptResult(passed=True)
    │
    └── exhausted → RepromptResult(passed=False, exhausted=True)
        on_exhausted: "return_last" → return last response
        on_exhausted: "raise" → raise AgentActionsError
```

---

## Checkpoint and Resume

Per-record checkpointing enables interrupted runs to resume without reprocessing.

```
First run (interrupted at record 150 of 200):

  for each record:
      result = process_record(item)           ← LLM call (slow)
      _checkpoint_record(result, context)     ← SQLite write (instant)
          ├── set_disposition(source_guid, SUCCESS)
          └── save_checkpoint_records(output data)
      # record 150 → Ctrl+C here
      # SQLite has 150 SUCCESS dispositions + 150 output records

Re-run:

  _reset_retryable_actions():
      action was RUNNING → selective clear (failures only)
      150 SUCCESS dispositions preserved

  UnifiedProcessor.process():
      Step 2: assign same content-hash guids (deterministic)
      Step 3: DispositionGate finds 150 terminal IDs
              → carry forward from checkpoint_output table
              → only 50 records to process

      strategy.invoke(50 remaining records)
      → enrich + collect (all 200)
      → write final output
      → clear_checkpoint_records()
```

### Checkpoint storage

```
checkpoint_output table:
    UNIQUE(action_name, relative_path, source_guid)
    INSERT OR REPLACE (upsert)

    ┌──────────────┬──────────────┬──────────────┬────────────┐
    │ action_name  │relative_path │ source_guid  │record_data │
    ├──────────────┼──────────────┼──────────────┼────────────┤
    │ summarize... │ combined.json│ 44462716-... │ {JSON...}  │
    │ summarize... │ combined.json│ 973062f1-... │ {JSON...}  │
    └──────────────┴──────────────┴──────────────┴────────────┘
```

### Cleanup paths

Every path that resets action state also clears checkpoint records:

| Path | When | Code |
|------|------|------|
| Normal completion | After `save_main_output` | `pipeline.py:591` |
| `--fresh` | At workflow startup | `coordinator.py:285` |
| `retry` command | Per downstream action | `cli/retry.py:201` |

---

## Disposition Gate — What Gets Reprocessed

```
TERMINAL_DISPOSITIONS (not reprocessed on re-run):
  ✓ SUCCESS
  ✓ FILTERED
  ✓ SKIPPED
  ✓ PASSTHROUGH
  ✓ EXHAUSTED

NOT terminal (reprocessed on re-run):
  ✗ FAILED     ← user can fix the input and retry
  ✗ DEFERRED   ← in-flight batch/HITL, not done yet
```

On resume, `build_carry_forward()` reads prior output for carried records:

```
try read_target(action_name, relative_path)     ← completed action
except FileNotFoundError:
    read_checkpoint_records(action_name, path)   ← interrupted action
    if found → use as carry-forward data
    else → reprocess all
```

---

## Evaluation Loop (Batch Only)

The `EvaluationLoop` is used exclusively in the batch path for post-retrieval validation.

```
Batch results retrieved from provider
    │
    ▼
EvaluationLoop.split(results)
    │
    ├── graduated (passed validation) → never re-evaluated
    └── still_failing → resubmit with feedback prompt
                         │
                         ▼
                    provider API (new batch)
                         │
                    EvaluationLoop.split(new_results)
                         │
                         └── repeat until pass or exhausted
```

The graduated pool pattern: each round, only failing records are resubmitted. Graduated records accumulate permanently. The failing set can only shrink.

---

## Invariants and Caveats — What Breaks If You Change Things

Read this before modifying processing code. These are the non-obvious constraints that have caused real bugs.

### Ordering constraints (step sequence matters)

```
source_guid assignment (step 2) MUST happen BEFORE DispositionGate (step 3)
    Why: the gate matches records by source_guid. First-stage records don't
    have one from staging files. If you move guid assignment after the gate,
    checkpoint resume stops working — the gate can't match anything.
    Bug found: 2026-05-31 during checkpoint testing.

Guard filter (step 1) MUST happen BEFORE source_guid assignment (step 2)
    Why: generate_content_hash(record) hashes ALL keys in the dict. If the
    guard evaluator adds metadata fields to the record dict before hashing,
    the hash will differ between runs (guard may evaluate differently based
    on prior state). The guard must not mutate passing records.

Enrichment (step 6) MUST happen BEFORE collection (step 7)
    Why: collection stamps _state on records. Downstream actions validate
    _state exists. If you collect before enriching, the lineage fields
    are missing and downstream breaks.

Carry-forward records MUST bypass enrichment (step 8, after step 6)
    Why: they already have correct lineage from the prior run. Re-enriching
    would overwrite their node_id, target_id, and lineage with duplicates.
```

### source_guid identity contract

```
source_guid is the ONLY record identity used across the entire pipeline:
  - DispositionGate matches by source_guid
  - Checkpoint records keyed by source_guid
  - Dispositions keyed by (action_name, record_id=source_guid)
  - Carry-forward lookup: prior_by_guid[source_guid]
  - Cascade filter checks record._state by source_guid

For first-stage records: source_guid = UUID5 content hash (deterministic).
    Same input dict → same guid every run.
    Assigned in UnifiedProcessor.process() line 121-126.
    TaskPreparer._normalize_input() PRESERVES existing guid (line 142-144).
    If you break this (e.g., generate a new uuid4), checkpoint resume fails:
    the gate looks for the content-hash guid but the checkpoint stored uuid4.
    Bug found: 2026-05-31, took 3 debugging rounds to identify.

For non-first-stage records: source_guid comes from upstream action output.
    Already set on the record dict when it enters the pipeline.
```

### Disposition write ordering (checkpoint vs collection)

```
Per-record checkpoint writes happen DURING invocation (step 5):
    _checkpoint_record() → set_disposition(SUCCESS) + save_checkpoint_records()

Batch collection writes happen AFTER enrichment (step 7):
    collect_results_from_processing_results() → set_dispositions_batch()

Both write to the SAME disposition table with UNIQUE(action_name, record_id, disposition).
The collection write overwrites the checkpoint write. This is intentional and idempotent:
    - Checkpoint writes SUCCESS, collection writes SUCCESS → same value
    - Checkpoint writes SUCCESS, but parse-error detected → collection writes FAILED
      (this is the correct final disposition)

If you remove the collection write thinking "checkpoint already wrote it":
    - Parse-error reclassification breaks (SUCCESS → FAILED won't happen)
    - SKIPPED/FILTERED/EXHAUSTED dispositions are never written (checkpoint
      only writes SUCCESS/FAILED, not guard outcomes)
```

### _state mutation contract

```
_state is stamped by result_collector.py during collection (step 7).
Checkpoint records need _state=PROCESSED stamped BEFORE saving to the
checkpoint table, because build_carry_forward returns them directly to
the output list without going through collection again.

If you remove the _state stamping in _checkpoint_record():
    Downstream actions reject carried-forward records with:
    "Record is missing '_state'. Delete agent_io/target/ and re-run."
    Bug found: 2026-05-31 during real workflow testing.

Checkpoint stamps _state on COPIES of result.data, not in-place:
    checkpoint_records = [{**item, "_state": PROCESSED} ...]
    Why: result.data dicts are shared references. In-place mutation
    would affect the enrichment pipeline and event payloads that hold
    references to the same dicts.
```

### Cascade filter depends on upstream _state

```
cascade_filter.py checks record["_state"] against CASCADE_BLOCKING_VALUES:
    {"cascade_skipped", "failed", "exhausted"}

If upstream writes a tombstone without _state (or with wrong _state):
    The cascade filter won't quarantine it → downstream tries to process
    a tombstone as a real record → garbage output or crash.

If you add a new RecordState value that should block downstream:
    Add it to CASCADE_BLOCKING_VALUES in record/state.py.
    If you forget, downstream actions will try to process failed records.
```

### Every reset path must clear checkpoint records

```
Three places clear action state. ALL THREE must clear checkpoint_output:

1. pipeline.py:591      — after save_main_output (normal completion)
2. coordinator.py:285   — _clear_for_fresh_run (--fresh flag)
3. cli/retry.py:201     — RetryCommand.execute (retry command)

If you add a new reset path (e.g., a new CLI command that resets actions):
    You MUST also call storage_backend.clear_checkpoint_records(action_name).
    If you forget: stale checkpoint data from a prior run is silently
    carried forward instead of reprocessing. The output looks correct but
    contains stale data from a different run.
    Bug found: 2026-05-31 during /simplify review.
```

### RUNNING_CLEAR_DISPOSITIONS — selective vs bulk clear

```
When _reset_retryable_actions resets action statuses to PENDING:

  MID_PROCESSING_STATUSES (RUNNING, INTERRUPTED)
                 → clear only RUNNING_CLEAR_DISPOSITIONS
                    (FAILED, EXHAUSTED, DEFERRED)
                    Preserves: SUCCESS, PASSTHROUGH, FILTERED, SKIPPED

  All other retryable statuses (FAILED, SKIPPED, CHECKING_BATCH)
                 → bulk clear ALL dispositions

Why the asymmetry:
  RUNNING = interrupted mid-processing. May have checkpointed SUCCESS
  dispositions that should survive for carry-forward on resume.

  FAILED = zero successes by definition (_resolve_completion_status only
  returns FAILED when has_successful_items() is False). Nothing to preserve.

  SKIPPED = no records processed. Nothing to preserve.

If you add COMPLETED_WITH_FAILURES back to RETRYABLE_STATUSES:
    You reintroduce the v0.2.2 rewind bug — the workflow goes back to
    earlier actions instead of finishing the current run.
    Bug found: spec 534, 2026-05-31.
```

### FILE mode ordering matters

```
In UnifiedProcessor.process(), result ordering differs by mode:

  FILE mode:  quarantined + invocation + guard
  RECORD mode: guard + quarantined + invocation

This is intentional. FILE mode workflows depend on sequential accumulation
(record N can reference record N-1's output). Do not unify without
verifying FILE-mode workflows that depend on positional ordering.

Also: FILE mode rebuilds context.source_data from `processable` after the
disposition gate and cascade filter, replaying both onto it so index i still
names the record the strategy receives at index i. It is rebuilt rather than
pruned by guid because the gate re-queues un-carryable records at the END of
the work list, which pruning alone would leave misaligned. If you skip this,
FileToolStrategy.reconcile_outputs() matches records by wrong indices and
HITLStrategy attributes each reviewer decision to the wrong record.
```

---

## File Map

| File | Purpose |
|------|---------|
| `unified.py` | Pipeline skeleton, `ProcessingStrategy` protocol, `UnifiedProcessor` |
| `types.py` | `ProcessingResult`, `ProcessingContext`, `ProcessingStatus`, metadata types |
| `strategies/online_llm.py` | Per-record LLM loop, checkpoint, response transform |
| `strategies/file_tool.py` | FILE-granularity tool invocation + output reconciliation |
| `strategies/hitl.py` | FILE-granularity HITL broadcast |
| `invocation/strategy.py` | `InvocationStrategy` ABC, `BatchProvider` protocol |
| `invocation/online.py` | `OnlineStrategy` — sync LLM call with retry + reprompt |
| `invocation/batch.py` | `BatchStrategy` — deferred queue + flush |
| `invocation/factory.py` | `InvocationStrategyFactory` — builds strategy from config |
| `invocation/result.py` | `InvocationResult` — immediate / filtered / queued |
| `enrichment.py` | `EnrichmentPipeline` and 6 enrichers |
| `result_collector.py` | Flatten results → output records + dispositions |
| `disposition_gate.py` | `DispositionGate` + `build_carry_forward` |
| `cascade_filter.py` | Quarantine upstream-failed records |
| `guard_context.py` | Build field context for guard evaluation |
| `task_preparer.py` | `TaskPreparer.prepare()` — normalize, guard, prompt |
| `prepared_task.py` | `PreparedTask`, `GuardStatus`, `PreparationContext` |
| `record_helpers.py` | Tombstone builders, `derive_relative_path` |
| `exhausted_builder.py` | Build exhausted retry tombstones |
| `source_resolution.py` | Identity resolution for non-first-stage content — own guid, then parent_source_guid, then None |
| `batch_context_adapter.py` | Bridge batch state into `ProcessingContext` |
| `error_handling.py` | `ProcessorErrorHandlerMixin` |
| `recovery/retry.py` | `RetryService` — transport-layer retry with backoff |
| `recovery/reprompt.py` | `RepromptService` — validation-layer reprompt |
| `recovery/response_validator.py` | Schema + UDF validators, `ComposedValidator` |
| `recovery/critique.py` | LLM self-critique for stubborn failures |
| `recovery/validation.py` | Thread-safe UDF registry |
| `evaluation/loop.py` | `EvaluationLoop` — graduated pool (batch only) |
| `evaluation/strategies/validation.py` | `ValidationStrategy` — batch result validation |
| `evaluation/exhaustion.py` | `apply_exhausted_reprompt` metadata stamping |

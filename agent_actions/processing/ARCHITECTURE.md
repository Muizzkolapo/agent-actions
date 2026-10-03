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
   (what to do)     (how to call it)       (transport retry)
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
                                         (batch repair
                                          rounds)
```

The module has **five concerns**:

| Concern | Where | What it does |
|---------|-------|-------------|
| Pipeline skeleton | `unified.py` | Guard → cascade → invoke → enrich → collect |
| Strategies | `strategies/` | Per-record LLM, file-level tool, file-level HITL |
| Invocation | `invocation/` | Online (sync + retry + expectations) vs batch (deferred queue) |
| Recovery | `recovery/` | `RetryService` (transport errors); validation-layer recovery lives in `expectations/` |
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
│  unified.py:150-162                                  │
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
│  unified.py:116-119                                  │
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
│  disposition_gate.py:125-165                         │
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
│  │       → OnlineStrategy: LLM call wrapped in     │ │
│  │         retry, then the expectations loop       │ │
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
│                           (retry details)            │
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
          │     ├── retry only:   RetryService.execute(llm_call)
          │     ├── expect only:  ExpectationService.execute(llm_call)
          │     ├── both:         expectations(retry(llm_call))
          │     └── neither:      direct llm_call
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

### Expectations (validation-layer recovery)

```
ExpectationService.execute(llm_operation, original_prompt)
    │                                       expectations/service.py
    for iteration in 1..max_iterations:
    │   response = llm_operation(current_prompt)
    │   │
    │   ├── Structural gate (skipped only in observe mode)
    │   │     → non-record or schema-non-conforming response becomes
    │   │       a synthetic `_structural` failing outcome, and
    │   │       `structural:` picks how it is regenerated
    │   │
    │   ├── Suite runs every expectation over the record
    │   │     → each outcome carries severity, detail and hint
    │   │
    │   ├── Any `error` outcome? `repair:` decides the next prompt:
    │   │     retry → re-send the original
    │   │     auto  → original + the failure detail, hint and last output
    │   │
    │   └── Suite passes → return the response with its verdict attached
    │
    └── exhausted → on_exhausted decides:
        "return_last" → ship the annotated last attempt
        "fail"        → executed=False, response None, verdict kept
        "raise"       → raise ExpectationsExhaustedError
```

`repair: none` is observe mode: one unlooped pass that attaches a verdict and
never consults the schema.

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
| Normal completion | After `save_main_output` | `pipeline.py:618` |
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

A record resolves either by its own `source_guid` or through the rows it produced,
matched on their `producer_source_guids`: an action that mints an identity per output
row holds none carrying its input's, so an input resolvable only the second way would
be re-queued and reprocessed on every run. Every row a producer made comes back, since
the input is the whole group's only identity.

Neither reading may return a row under an identity this run is already writing, or the
carried copy lands beside the run's own and the identity is stored twice. The caller
therefore names every such identity, not only the records it reprocesses: the guard runs
*above* the gate, so a guard-skipped record is in no carry set and still writes a
tombstone of its own. A merge row keyed on it answers for its other producers too, so
refusing it reports those as `missing` and the caller re-queues them — dropping the row
on its own would take their content with it, since the run does not re-invoke the tool.

The batch path rewrites its output file whole and asks the mirrored question — which
*stored* rows the run did not write again — through `stored_rows_not_reproduced()`. Two
runs of a minting action share no identity, so comparing identities carries every stale
row back beside its replacement. Matching is therefore by input, and only a row settled
as `processed` answers for one: the producers it names, else the identity it carries.

Both readings are needed because how many rows an input yields is decided per run from
what the provider returned. The same input mints several rows one run and keeps its own
identity the next, and each direction is a replacement: read only the producers and a
count falling to one leaves the minted rows behind, read only the identities and a count
rising leaves the single row behind.

The `processed` condition guards both. A failed or exhausted row is keyed on its input
and holds no answer; and because producers are named during enrichment, before
collection settles the state, a row can name an input it holds nothing for. Either
credited as an answer deletes what the last run produced. Such a row does still replace
a stored row of its own identity, which is decided first — carried rows are appended to
the run's own output, so an identity in both lists would be written twice.

A stored row naming exactly one input is inferred away; naming several, never. That
reads one producer as a mint, which holds on this path — a batch row that names producers
has been re-keyed — but not in general. The FILE writer records the inputs a row consumed
*minus* its own, so a two-input merge keeps one identity and names one producer; inferred
away, its own input's content goes with it. `build_carry_forward` carries the stricter
reading for rows of that shape, and a future caller reading them wants it rather than
this. Where several inputs are named the row is handed back regardless, a duplicate being
visible where a dropped row is not.

Matching by input still leaves one case open: where the action above is *itself* an
expansion, its children are minted again every run, so a stored row names a producer this
run's rows never name and neither generation replaces the other. The two are told apart by
what the action took as input — a producer named by none of it is a generation that is
gone, one still standing in the input is an input this run did not answer for. That set is
not the batch context map, which holds only what was submitted. Several narrowings sit
between the two — the action's `record_limit`, a repair's named records, the disposition
gate, and above the pipeline entirely the runner's drop of records an upstream guard
filtered — and a record dropped by any of them still holds stored rows this action must
carry. So the pipeline hands the batch path the same pre-narrowing input it already hands
the online path (`offered_to_repair`), submission records it
(`BatchContextManager.save_batch_inputs`), and the merge reads it back. Reading anything
narrower deletes the rows of every record the run left out: on an ordinary incremental run
that is everything already done, and on `agac retry` everything the repair did not name.
The recording sits above the pipeline's own narrowings but not above the runner's, which is
why the rule below is generational — what the recording cannot be trusted to include, the
rule does not decide from.

Because the inference deletes, it is made only where the evidence is whole. Three
conditions, all of them: the input was recorded at all; this run settled *every* input it
recorded, so what replaces the stored generation is actually in this write; and *no* stored
producer is still an input. The second stops a run that failed, or returned nothing, from
reading its own stored answers as replaced and deleting them. The third makes the decision
generational rather than per row — one producer missing while others are still inputs is an
individual record that left the input, filtered upstream or dropped, and its rows are its
own. An unrecorded input infers nothing, so a batch submitted before this was recorded
carries its rows exactly as it did; an input recorded as empty is reported apart from an
unrecorded one but read the same way. A drop is logged once per write at INFO, not WARNING,
with how many rows went and the counts that decided it, since the healthy re-run this case
exists for makes one every time.

That rule reads identities alone, and an identity cannot tell an upstream action minting
its children again from a record that left the input or one a guard held back. So it
accumulates below an expansion for an action that mints nothing (#1155), and drops the rows
of records that merely left (#1206). A batch run now records two more things, and where
both are present `_carried_by_ancestor` decides instead:

- beside each input, the staged record it descends from: its `parent_source_guid` where it
  has one, else its own identity;
- the upstream pool for the file as the runner read it, above its drop of guard-filtered
  records, with each identity's staged record. A filtered or deferred record is absent from
  its action's output, so those identities are added from the dispositions.

A stored row is dropped only where the input it answered for is gone from that pool while
the run has inputs descended from the same staged record -- the children were minted again
-- and settled (answered or guard-skipped) every one of them, so the replacement is in this
write. A row whose input is still in the pool was held back or narrowed past and is kept; so
is one whose staged record no input descends from, and one merging several inputs. With no pool recorded nothing is known to be gone and every row not answered again
is kept. A run recorded before any of this is read by the identity rule above, unchanged;
the strict xfail in `tests/unit/processing/test_superseding_is_limited_to_one_producer.py`
pins that path.

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

1. pipeline.py:618      — after save_main_output (normal completion)
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

  FAILED = zero successes whenever _resolve_completion_status classified it
  (it returns FAILED only when has_successful_items() is False). An action
  that raised instead of returning is also FAILED and may hold successes:
  their output survives the clear, their dispositions do not, so those
  records are processed again on the next run.

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
| `invocation/online.py` | `OnlineStrategy` — sync LLM call with retry + expectations |
| `invocation/batch.py` | `BatchStrategy` — deferred queue + flush |
| `invocation/factory.py` | `InvocationStrategyFactory` — builds strategy from config |
| `invocation/result.py` | `InvocationResult` — immediate / filtered / queued |
| `enrichment.py` | `EnrichmentPipeline` and 6 enrichers |
| `result_collector.py` | Flatten results → output records + dispositions |
| `disposition_gate.py` | `DispositionGate` + `build_carry_forward` + `stored_rows_not_reproduced` |
| `cascade_filter.py` | Quarantine upstream-failed records |
| `guard_context.py` | Build field context for guard evaluation |
| `task_preparer.py` | `TaskPreparer.prepare()` — normalize, guard, prompt |
| `prepared_task.py` | `PreparedTask`, `GuardStatus`, `PreparationContext` |
| `record_helpers.py` | Tombstone builders, `derive_relative_path` |
| `exhausted_builder.py` | Build exhausted retry tombstones |
| `source_resolution.py` | Identity resolution for non-first-stage content — own guid, then parent_source_guid, then the `source` namespace the record carries (which must be a dict), then None |
| `batch_context_adapter.py` | Bridge batch state into `ProcessingContext` |
| `error_handling.py` | `ProcessorErrorHandlerMixin` |
| `helpers.py` | Shared processor utilities — dynamic agent call, schema echo rejection, passthrough transform |
| `recovery/retry.py` | `RetryService` — transport-layer retry with backoff |
| `recovery/response_validator.py` | Schema + UDF validators, `ComposedValidator` |
| `evaluation/loop.py` | `EvaluationLoop` — graduated pool (batch only) |
| `evaluation/strategies/expectations.py` | `ExpectationStrategy` — batch result validation |

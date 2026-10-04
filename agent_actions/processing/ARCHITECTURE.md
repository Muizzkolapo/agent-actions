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
the run's own output, so an identity in both lists would be written twice. The one
exception is a run online would refuse to write, below: there the stored answer is the one
row kept under that identity.

Which unanswered rows come back is the online path's rule. Online writes rows for this
run's inputs and nothing else: what it processed, and what the gate carried. So a stored
row is carried where the input it answered for is one of the run's and the run did not
answer it again, and a row whose input is not among them is left out. Below an expansion
that is what stops the output growing: the upstream children are minted again every run, so
the previous generation's rows answer for inputs this run never took.

"This run's inputs" is not the batch context map, which holds only what was submitted.
The action's `record_limit` and the disposition gate both sit between the two, and a record
either drops is still an input whose stored rows must be carried. So the pipeline hands the
batch path the same pre-narrowing input it already hands the online path
(`offered_to_repair`), submission records it (`BatchContextManager.save_batch_inputs`), and
the merge reads it back. Reading anything narrower deletes the rows of every record the run
left out, which on an ordinary incremental run is everything already done.

Two kinds of run carry more than their inputs' rows, each because online does:

- **A repair records no inputs.** `agac retry` answers the records it named and nothing
  else, and online hands back every stored row it did not name (`carried_past_repair`). A
  stored row can sit under an identity the repair's input does not derive -- its record
  absent that run, or stored under another file's identity -- and read against the inputs it
  would be left out. With nothing recorded every unanswered row is carried, which is also
  what a batch submitted before inputs were recorded gets. The repair's submission removes
  any recording an earlier run left, so that does not rest on who cleared batch state first.
- **A run in which something failed and nothing was answered replaces no answer.** Online
  raises before it writes when nothing succeeded (`raise_if_terminal_failure`), so its
  stored answers stand. Here
  the failures are written, beside every stored answer whichever input it was for; a
  failure row under a stored answer's own identity gives way to it, so the identity is
  still stored once. Stored rows that are not answers follow the inputs as usual. Without
  a failure the run did produce this run's file, however little is in it, and the inputs
  rule applies in full, as online writes it. A record that fails prompt preparation when
  nothing else is sent is such a failure: it reaches the write as a failed row.

A row naming several inputs is always carried: it holds what each gave it, so no one input
accounts for it, and a duplicate is visible where a dropped row is not. What is left out is
logged once per write at INFO with the counts, since a healthy re-run below an expansion
leaves rows out every time.

Leaving a row out is safe only because an input that returns is answered again. The gate
carries any input with a terminal disposition, and one whose row was left out has the
disposition and no row. Online re-queues those (`build_carry_forward` reports them
`missing`); submission does the same, looking the stored file up under the name finalize
writes it (`batch_output_name`), so the two cannot disagree about whether a row exists. An
input the guard filtered is not looked up, since it holds no row by design. It is sent on
to the guard again instead: online's guard runs above its gate and judges every input
afresh, where the gate here would call a filtered one done for good.

When the guard leaves nothing to send, submission returns a tombstone that the caller
writes as a whole file. It goes through the same merge (`with_stored_rows_not_reproduced`),
so that write carries what a finalize would. Alone it replaced every stored answer with
nothing while their dispositions still said done. The rows are read from, and the tombstone
written to, the one file finalize writes: `batch_output_name` of the batch's name, which
submission derives itself rather than taking a path from its caller, so the two cannot
drift.

A batch input file has one name, its identity: its path under the action's input root
(`sub/page.json`; a top-level file's is its name, as it always was). Its registry entry,
context map, recorded inputs, recovery state and recovery entries are keyed by it, and its
output is stored under `batch_output_name` of it: `sub/page.json`, where online stores the
same file, and the name every action below then reads it under. Keyed by the basename, as
it was, two files of one name in two directories shared one batch and the second was never
sent, and a nested file's answers and its nothing-to-send write were two files. A store
written then holds a nested file, its batch state and every downstream join under the
basename, and moving them would break the joins. So `batch_file_identity` keeps the
basename for a file the store already holds under it (its output, or a registry entry),
unless a top-level input of the action stores under that name or another nested file
stored under it claimed it first. The choice is recorded per action
(`batch_file_names:{action}`) and follows the stored rows, not the inputs of the day: a
reset keeps it, `--fresh` removes it, and a repair records none. What this leaves:

- A store that already holds a file under both names (answers under `page.json`, a
  nothing-to-send write under `sub/page.json`) keeps the nested file as it stands. Nothing
  writes it again, its rows count twice toward a record limit, and `--fresh` clears it.
- Two files of one basename that collided in a store written before: the first walked keeps
  the flat name. Where that file held the other one's rows, both are sent again, once.
- A nested file first seen after a top-level file of its basename has left takes the flat
  name the departed file was stored under.
- Two inputs in one directory that differ only by suffix (`sub/page.csv`, `sub/page.json`)
  still share one stored name, as they do online.
- Code before this cannot read a key with a directory in it, so a store this code wrote
  cannot be run by it again.

The two paths do not always leave the same file. Where batch differs it holds more, with
one exception noted last:

- A run whose every input the gate carries submits nothing and finalizes nothing, so the
  file is left as it stands. It can still hold rows of inputs that have left; online writes
  the file again without them and answers them again when they return. A record that moves
  from one input file to another is answered in its new file while the old one, if nothing
  is submitted for it, still holds its row.
- Rows of inputs a record limit holds back are carried, since they are still inputs. Online
  drops them and answers them again when the limit admits them.
- A run in which something fails and nothing succeeds writes its failed rows. Online writes
  nothing.
- The gate runs above the guard here, so an answered input that now fails the guard keeps
  its answer. Online replaces it with a tombstone, or with nothing.
- An expanding input sent again that fails, while something else succeeds, keeps the rows
  it minted before beside its failure row. Online holds the failure row alone.
- A row naming several inputs is always carried.
- The exception: an online run that raised wrote nothing, so its file still holds answers
  for records that are no input of that run. A batch run over the same inputs that writes
  a file, whether it answered something or wrote only what the guard left, writes this
  run's file, without them. Batch holds less there only because online's run aborted, and
  never for a record that is an input of the run.

An empty answer goes by the action's `on_empty` on both paths. `warn` stores a failed row
and `skip` a tombstone, the same in each. Under `error` online raises at the record and
stores nothing; a batch stores the record as failed with the other answers, since a batch
has one write and they are in it, and then halts: the halt leaves the loop over the
action's files and the executor records the action as failed. An empty answer is never a
success with nothing stored, which left the record done with no row and nothing saying
the model had returned nothing. Two things are not empty answers here: a result whose
content is null is a provider failure (a refusal, a safety block), retried where `retry` is
on and stored failed otherwise,
and when an expanding input sent again answers empty under `skip`, the rows it minted
before stay beside its tombstone, as they do beside a failure row.

`tests/integration/test_batch_rerun_matches_online.py` drives both paths from
`ProcessingPipeline.process` against a real store. For every input of a run it requires
that batch never loses an answer online still holds, never leaves unanswered what online
answers, and never pays for an input twice running where online did not.

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

  MID_PROCESSING_STATUSES (RUNNING, INTERRUPTED, CHECKING_BATCH)
                 → clear only RUNNING_CLEAR_DISPOSITIONS
                    (FAILED, EXHAUSTED, DEFERRED)
                    Preserves: SUCCESS, PASSTHROUGH, FILTERED, SKIPPED

  All other retryable statuses (FAILED, SKIPPED)
                 → bulk clear ALL dispositions

Why the asymmetry:
  RUNNING = interrupted mid-processing. May have checkpointed SUCCESS
  dispositions that should survive for carry-forward on resume.

  CHECKING_BATCH = died while collecting a batch. The files it reached are
  written and their records done. A finished batch job stops its file being
  submitted again only until it is collected, so with those dispositions
  wiped each collected file is submitted, and paid for, a second time.

  A collect pass that ends in an error, not a kill, is marked FAILED by the
  error handler. It holds what it collected all the same, so the state
  manager records that it was stopped while collecting (`stopped_collecting`)
  and the reset clears it selectively too. The mark goes with the next status
  change, so the protection covers one reset: if the resumed run then fails
  while running, before it is back to collecting, the reset after that wipes.

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

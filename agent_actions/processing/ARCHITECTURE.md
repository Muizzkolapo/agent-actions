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
│  │       → write output then disposition to SQLite │ │
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
│  Flush dispositions in single SQLite transaction;    │
│  online, SUCCESS/PASSTHROUGH wait for the file write │
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
          ├── save_checkpoint_records(output data)
          └── set_disposition(source_guid, SUCCESS)   ← only once the row is stored
      # record 150 → Ctrl+C here
      # SQLite has 150 SUCCESS dispositions + 150 output records

Re-run:

  _reset_retryable_actions():
      action stopped partway, config unchanged → selective clear (failures only)
      150 SUCCESS dispositions preserved

  UnifiedProcessor.process():
      Step 2: assign same content-hash guids (deterministic)
      Step 3: DispositionGate finds 150 terminal IDs
              → carry forward from checkpoint_output table
              → only 50 records to process

      strategy.invoke(50 remaining records)
      → enrich + collect (all 200)
      → write final output
      → write_dispositions(SUCCESS, PASSTHROUGH)
      → clear_checkpoint_records(action, that file)
```

A checkpoint row left beside a stored file is therefore a later answer than the row
stored for that record: the run that gave it stopped before writing the file again,
after an edit or an upstream change had reset the action. `answered_since_stored`
names those records and the online path answers them again. The stored row is not
the answer their disposition describes, and the checkpoint row is the strategy's
output before enrichment, without lineage or metadata. Carrying checkpoint rows is
kept for a file with nothing stored.

That makes the row the only sign a record was answered after its file was stored, so
`_checkpoint_record` stores it before the disposition the gate carries, and writes no
disposition when the row's write fails. Committed the other way round, a run stopped
between the two, or a failed row write, left a record marked answered with no row, and
the next run carried the stored row from before the reset.

Collection marks a record answered only once its file is stored (see "Disposition write
ordering" below), so a record whose row write failed is asked again however the run stops
before that write.

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

`relative_path` is the name the file's output is stored under:
`ProcessingContext.target_relative_path`, set by the caller that writes the file
(`pipeline.py` from what `save_main_output` writes, `initial_pipeline.py` from its
`.json` output path). That is the file's path below the input root, so a file in a
subdirectory is `sub/page.json` and a staged `page.csv` is `page.json`. Carry-forward,
the carry of a repair, the checkpoint, `answered_since_stored` and the clear after a
write all use it. A resume reads the stored file, answers again a record checkpointed
beside it, and falls back to the checkpoint by that one name only where nothing is
stored; a repair that cannot find the stored file has nothing to carry and rewrites it
with only the records it named. Writing a file clears that name's checkpoint rows and no
other's, so a resume that saves one file still carries the checkpoint of a file it
reaches after it.

### Cleanup paths

Every path that resets action state also clears checkpoint records:

| Path | When | Code |
|------|------|------|
| A file written | After its write, that file's rows only | `pipeline.py`, `initial_pipeline.py` |
| An action reset to run again | `reopen_with_readers` | `executor.py` (`_forget_what_it_did`) |
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
answered_since_stored(action_name, path)        ← checkpointed after the file
    → not carried: answered again                  was stored (online path)
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

An input the guard filtered holds no row, whether or not the run recorded its inputs:
online's guard runs above its gate and writes nothing for it. Its stored rows answer for a
record the guard now excludes, and carried they reach every action below; where the guard
filters every input they also keep the action reading complete over them, so its readers
are never skipped. The batch's context map says which inputs the guard filtered
(`filtered_inputs`), and both writes hand them to the merge, which carries no stored row
that answers for one. A run online would refuse to write, below, is the exception: online
writes nothing then, so a filtered input keeps what it held, answer or not, until a run
that writes.

Two kinds of run carry more than their inputs' rows, each because online does:

- **A repair records no inputs.** `agac retry` answers the records it named and nothing
  else, and online hands back every stored row it did not name (`carried_past_repair`). A
  stored row can sit under an identity the repair's input does not derive -- its record
  absent that run, or stored under another file's identity -- and read against the inputs it
  would be left out. With nothing recorded every unanswered row but a filtered input's is
  carried, which is also what a batch submitted before inputs were recorded gets. The
  repair's submission removes any recording an earlier run left, so that does not rest on
  who cleared batch state first.
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
logged once per write at INFO with the counts, one line for rows whose input is not the
run's and one for rows whose input the guard filtered, since a healthy re-run below an
expansion leaves rows out every time.

Leaving a row out is safe only because an input that returns is answered again. The gate
carries any input with a terminal disposition, and one whose row was left out has the
disposition and no row. Online re-queues those (`build_carry_forward` reports them
`missing`); submission does the same, looking the stored file up under the name finalize
writes it (`batch_output_name`), so the two cannot disagree about whether a row exists. An
input the guard filtered is not looked up, since it holds no row by design. It is sent on
to the guard again instead: online's guard runs above its gate and judges every input
afresh, where the gate here would call a filtered one done for good.

When preparation leaves nothing to send -- the guard skipped or filtered every input, the
action above blocked it, or its prompt could not be prepared -- submission collects and
writes the file itself, by the two functions finalize uses (`llm/batch/services/collect.py`).
`collect_batch_rows` runs the context map through `BatchResultStrategy` and the shared
collector with no results, so each row keeps the parent, version correlation and history
the action above gave it, and each record gets the disposition a run that sends gives it:
`unprocessed` for a guard skip or an upstream block, `filtered`, or `failed` with the
error. `write_batch_file` merges the stored rows the run does not replace
(`with_stored_rows_not_reproduced`) -- alone, the write replaced every stored answer with
nothing while their dispositions still said done -- and stores the file under
`batch_output_name` of the batch's name, the one file finalize writes, building the path
from that name so the two cannot drift. Submission then records the node-level
`passthrough` (with no rows stored, the action reads skipped) and raises any halt the
collect step returned, after the write as finalize does. Nothing touches the registry,
recovery state or batch events: no batch was sent. A record whose prompt cannot be
prepared is recorded failed with the error preparation raised, on both paths: it is kept on
the record's context-map entry (`_batch_prep_error`), since a collect pass may run in a
later process. A map saved before the key existed records `prep_failed`.

When no record is left to send at all -- the gate carries every input, or the input holds
none -- nothing is sent or collected, but the file is still this run's, as online writes
it every run. Submission merges the stored rows over no answers with this run's inputs, the
merge finalize makes, and stores the file under `batch_output_name` (`store_batch_file`).
So a row whose input has left goes, and a record moved to another file of the action is
answered there and held there alone; rows of inputs a record limit holds back stay, since
they are inputs. An empty input is written empty: handed to the merge, no inputs read as
none recorded and keep every row. Nothing is collected, since no batch or context map
exists for the run, and no node-level `passthrough` is recorded, so the action completes
as it did. A repair, or a run that recorded no inputs, writes nothing, so every row it did
not answer stands; and a file the merge would leave as it stands is not written again, as
on a resume where nothing left. The merge keeps one row per identity, so a file holding two
rows under one is written even then, with one of them, as online and finalize write it.
Where nothing is stored, none is made: online writes an empty input's file empty.

A batch input file has one name, its identity: its path under the action's input root
(`sub/page.json`; a top-level file's is its name). Its registry entry, context map,
recorded inputs, recovery state and recovery entries are keyed by it, and its output is
stored under `batch_output_name` of it, `sub/page.json`, the name every action below then
reads it under. Online stores a first-stage input and a `.json` input under that name too;
a later-stage input of another suffix (`page.txt`) online keeps as it is, where batch stores
`page.json` (an action stores its files under `.json` keys, so a later stage reading the
store does not meet one). Keyed by the basename, two files of one name in two directories
shared one batch and the second was never sent, and a nested file's answers and its
nothing-to-send write were two files.

A store written by an older version holds a nested file, its batch state and every
downstream join under the basename, and moving them would break the joins. So
`batch_file_identity` keeps the basename for a file the store already holds under it (its
output, or a registry entry), unless a top-level input of the action stores under that
name or another nested file stored under it claimed it first. In the first stage a
top-level input is a file directly under the staging root that the walk processes (its own
skip rule and the start node's `file_type` decide); in a later stage it is a dependency
storing that name, a version base counting as each of its versions. A file given its own
name over a basename the store holds is logged once, since any of its records held there
are sent again. The choice is recorded per action (`batch_file_names:{action}`) and follows
the stored rows, not the inputs of the day: a reset keeps it, `--fresh` removes it, and a
repair records its choice as any run does, so two files cannot claim one name within it.
What this leaves:

- A store the older version already split across two names (answers under `page.json`, a
  nothing-to-send write under `sub/page.json`) stays split. The file keeps `page.json`, and
  nothing writes `sub/page.json` again, but the actions below read both: they answer that
  file's records twice, and a record limit counts them twice, until `--fresh`.
- Two files of one basename that collided in such a store: the first walked keeps the flat
  name, and the other is sent again under its own. Where the flat file held only the
  other's rows, the first is sent again too. Where it held both files' rows, the flat file
  is written for the first file's inputs alone, which leaves the other's out: in that same
  run when every record of the first file is already answered, otherwise once its batch is
  collected, and until then the other's rows are read twice below.
- A nested file from the older version whose batch is still out when a top-level file of
  its basename appears moves to its own name in that run. Its records are sent a second
  time, and held under both names until the top-level file, which finds that batch under
  its own name and so waits a run, is sent and writes the flat file over.
- A store this version wrote can keep a nested file under the flat name too: a file moved
  into a subdirectory, or a nested file first seen after a top-level file of its basename
  has left, takes the name the departed file was stored under.
- Two inputs in one directory that differ only by suffix (`sub/page.csv`, `sub/page.json`)
  still share one stored name, as they do online.
- An older version runs a store this one wrote without error, but reads every key by the
  basename. It sends every record of a nested file again and stores a second copy under the
  basename, beside the one this version wrote, and it cannot load the context map of a batch
  this version left out, so that batch's answers are never stored. Run it with `--fresh`.
  Its `--fresh` leaves `batch_file_names` behind, so run `--fresh` again on coming back.

The two paths do not always leave the same file. Where batch differs it holds more, with
one exception noted last:

- A record that leaves a file while the file's batch is out, or finished and not yet
  collected, keeps its row: that run sends nothing for the file, and the collect merges over
  the inputs recorded when the batch was sent. Online writes the file again without it.
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

Dispositions differ where the rows do not:

- A guard skip is `unprocessed` here and `passthrough` online. The gate runs above the
  guard here, so a terminal disposition would carry the skip for good; `unprocessed` sends
  the record to the guard again on the next run.

A record with no `source_guid` is not among them: both paths refuse it at enrichment and
record nothing for it, under its target id or any other (see the identity notes below).

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

A record that arrives without one has no identity, in either mode, and is
    given none: no disposition is written for it under any other id.
    RequiredFieldsEnricher refuses what it produced, so it is stored as a failed
    row with no source_guid, keeping the target_id and content it arrived with;
    the exceptions are an expansion, whose rows LineageEnricher gives identities
    of their own, and a guard filter, which leaves nothing. Batch knows a sent
    record by its custom_id, which is its target_id, but never records it under
    that: a run whose input has none mints a new one, and nothing that selects a
    record reads it, so a failure there would be one `agac retry` names, clears,
    and cannot repair. BatchResultReconciler.get_source_guid returns None for it,
    and for an id the context map does not hold, such as a parser placeholder;
    submission marks it no `deferred`, and `--abandon-in-flight` marks it no
    `failed`. It is still sent to the model before it is refused, in both modes.

Refused, it leaves no disposition, and batch reads an action's outcome from
    dispositions alone. So where nothing in a file holding such a record
    succeeded, batch raises online's breaker (`terminal_failure`) once the file
    is written, and the executor records the action failed, as online. Where
    something succeeded, both read complete.

A batch run with nothing to send collects through the same step
    (`collect_batch_rows`), so there too such a record is recorded nowhere and
    stored as the same failed row. Nothing in such a run succeeds, so the same
    breaker is raised once the file is written.
```

### Disposition write ordering (checkpoint vs collection)

```
Per-record checkpoint writes happen DURING invocation (step 5):
    _checkpoint_record() → save_checkpoint_records(), then set_disposition(SUCCESS)
    A schema echo is failed before either write: the store's echo gate records FAILED
    as it saves the row, and the SUCCESS written after it would replace that.

Batch collection writes happen AFTER enrichment (step 7):
    collect_results_from_processing_results() → set_dispositions_batch()

Online, what the gate carries a record from the stored file by (SUCCESS,
PASSTHROUGH) waits in ProcessingContext.kept_dispositions, and the caller
writes it after the file:
    pipeline.py          save_main_output() → write_dispositions()
    initial_pipeline.py  write_target()     → write_dispositions()

    Written before the file, a run stopped between the two (a full disk, a
    Ctrl-C at the write) left records marked done while the stored file held
    an earlier run's rows. After an edit upstream, the reset kept them and the
    gate carried those rows. A FILE tool leaves no checkpoint row to say the
    file is older, and a record whose checkpoint row failed has none either.

    The rest (FAILED, EXHAUSTED, DEFERRED, UNPROCESSED, FILTERED) is written
    at once, because a file whose records all failed or were exhausted raises
    before it is stored. A failure replaces the checkpoint's SUCCESS for a
    parse error, and a reset clears it; `agac retry` reads FAILED and
    EXHAUSTED. FILTERED is what a fan-in drops a record by (filter is
    authoritative), and a filtered record has no row to carry: the guard
    filters it again above the gate.

    Still written before the file: SKIPPED for a record the context scope drops
    (pipeline.py), which the scope pass drops again before the gate; and, at
    record granularity, the checkpoint's SUCCESS, whose checkpoint row tells
    answered_since_stored that the stored file is older.

    A row the store refuses as a schema echo is given no SUCCESS: the store
    records it FAILED as it writes the file, and a SUCCESS written after the
    file would replace that.

    A write the store fails for one file of several fails the action once the
    walk has written the others (output/ARCHITECTURE.md), so the next run
    answers that file rather than the action completing over its earlier rows.

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
These places clear action state. ALL must clear checkpoint_output:

1. pipeline.py, initial_pipeline.py — after a file's write, that file's rows
2. coordinator.py       — _clear_for_fresh_run (--fresh flag)
3. cli/retry.py         — RetryCommand.execute (retry command)
4. executor.py          — _forget_what_it_did (an action reset to run again)

Clearing every file's rows after one file's write loses the answers of a
file the run has not written yet: its stored rows are then carried instead.

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

  Stopped partway (RUNNING, INTERRUPTED, CHECKING_BATCH, FAILED), with the
  config its run recorded as it started (`answered_under`) still in force
                 → clear only RUNNING_CLEAR_DISPOSITIONS
                    (FAILED, EXHAUSTED, DEFERRED)
                    Preserves: SUCCESS, PASSTHROUGH, FILTERED, SKIPPED,
                    and the prompt traces of what it keeps

  Stopped partway, edited since (prompt, schema, guard, model)
                 → it and every action reading it are forgotten, prompt
                   traces too, and answer everything again
                   (ActionExecutor.reopen_with_readers)

  Stopped partway, nothing recorded (state from before the stamp)
                 → by status: selective for RUNNING, INTERRUPTED,
                   CHECKING_BATCH; bulk for FAILED

  SKIPPED        → bulk clear ALL dispositions

Why:
  A stopped action may hold checkpointed SUCCESS dispositions, however it
  stopped: killed (RUNNING), interrupted, killed while collecting a batch
  (CHECKING_BATCH: the files it reached are written and their records done),
  or stopped by an error (FAILED: an action that raised may hold successes).
  Wiped, they are answered again; a finished batch job stops its file being
  submitted again only until it is collected, so each collected file is
  submitted, and paid for, a second time.

  Kept after an edit, they are answers to another prompt or from another
  model, carried as current, and the action is stamped complete under the
  new config. Which config they were answered under is known only from
  the stamp the executor writes when it starts the action's work.

  A batch the provider refuses fails the action, and the walk raises it once
  every file is walked. The refusal sent and stored nothing, so what the action
  had answered before still stands, and the reset keeps it as it keeps any
  failed action's while the config is unchanged. Bulk-wiped, one refused file
  would send, and pay for, every answered record of every file again.

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
| `record_helpers.py` | Tombstone builders |
| `exhausted_builder.py` | Build exhausted retry tombstones |
| `source_resolution.py` | Identity resolution for non-first-stage content — own guid, then parent_source_guid, then the `source` namespace the record carries (which must be a dict), then None |
| `batch_context_adapter.py` | Bridge batch state into `ProcessingContext` |
| `error_handling.py` | `ProcessorErrorHandlerMixin` |
| `helpers.py` | Shared processor utilities — dynamic agent call, schema echo rejection, passthrough transform |
| `recovery/retry.py` | `RetryService` — transport-layer retry with backoff |
| `recovery/response_validator.py` | Schema + UDF validators, `ComposedValidator` |
| `evaluation/loop.py` | `EvaluationLoop` — graduated pool (batch only) |
| `evaluation/strategies/expectations.py` | `ExpectationStrategy` — batch result validation |

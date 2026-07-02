# Record Module Architecture

This document maps the moving parts of `agent_actions/record/` — the module that defines how every pipeline record is assembled, versioned, and transitioned through its lifecycle.

---

## High-Level Overview

```
                        agent_actions/record/
                              │
          ┌───────────┬───────┼───────────┬──────────────┐
          │           │       │           │              │
     envelope.py   state.py  tracking.py  disposition.py  lifecycle_read.py
     (assembly)   (enum +    (FILE mode) (state →        (load-time
                   sets)      provenance)  disposition)    validation)
                                    │
                              reasons.py
                              (string constants)
```

RecordEnvelope is a stateless utility — all methods are `@staticmethod` and return plain dicts. There is no `RecordEnvelope` instance. The module is the single authority for record content assembly: every action type, granularity, and strategy converges here.

---

## Record Envelope Structure

Every record that flows through the pipeline is a plain dict with this shape:

```
{
    "content": {                         ← namespaced action outputs
        "extraction": {"title": ".."},   ← action_name: action_output
        "classification": {"type": ".."},
    },
    "source_guid": "abc-123-...",        ← stable identity (UUID4)
    "version_correlation_id": "def-...", ← links versions across re-runs
    "_state": "processed",               ← current lifecycle state
    "_state_history": [                  ← audit trail (capped at 64)
        {
            "timestamp": "2026-06-02T...",
            "action": "extraction",
            "from": null,
            "to": "active",
            "reason": "initial",
            "detail": null
        },
        ...
    ],
    "_state_schema_version": 1,          ← history format version

    // Per-stage fields (rebuilt by enrichers, NOT carried forward):
    "target_id": "...",
    "node_id": "...",
    "parent_target_id": "...",
    "root_target_id": "...",
    "lineage": {...},
    "metadata": {...},
    "_unprocessed": {...},
    "_recovery": {...},
    "chunk_info": {...},
}
```

---

## Field Categories

The module defines four frozen sets that classify every framework field. These sets drive which fields are carried forward between pipeline stages and which are rebuilt.

```
RECORD_TRACKING_FIELDS (stable identity — set once, carried forward)
├── source_guid
└── version_correlation_id

RECORD_LIFECYCLE_FIELDS (cumulative — carried forward AND appended to)
├── _state_history
└── _state_schema_version

RECORD_STAGE_FIELDS (per-stage — rebuilt by enrichers, NOT carried)
├── target_id
├── node_id
├── lineage
├── metadata
├── content
├── _unprocessed
├── _recovery
├── parent_target_id
├── root_target_id
├── chunk_info
└── _state

_PERSISTENT_FIELDS = TRACKING_FIELDS | LIFECYCLE_FIELDS
    (everything that build() copies from input → output)

RECORD_FRAMEWORK_FIELDS = _PERSISTENT_FIELDS | STAGE_FIELDS
    (union of all framework fields — used to strip metadata
     from user content in scope_namespace, record_processor,
     and pipeline_file_mode)
```

Note: `_state` is a stage field, not a lifecycle field. It is set by `transition()` at each stage, not carried forward by `_carry_persistent_fields()`. History is carried; the current state value is not.

---

## The Three Build Methods

All three are `@staticmethod` on `RecordEnvelope`. All return new dicts.

```
┌──────────────────────────────────────────────────────────────────────┐
│  build(action_name, action_output, input_record)                     │
│                                                                      │
│  Normal record assembly. Wraps action_output under action_name       │
│  inside content, preserves upstream namespaces from input_record,    │
│  carries persistent fields (source_guid, version_correlation_id,     │
│  _state_history, _state_schema_version).                             │
│                                                                      │
│  action_output is stored by REFERENCE inside content.                │
│  Collision on action_name overwrites the existing namespace.         │
│                                                                      │
│  Used by: online strategy, batch result strategy, exhausted builder  │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  build_skipped(action_name, input_record)                            │
│                                                                      │
│  Guard-skipped record. Sets action_name namespace to None.           │
│  Does NOT set _unprocessed or metadata — callers add those.          │
│  Carries persistent fields same as build().                          │
│                                                                      │
│  Used by: tombstone builders (record_helpers.build_tombstone)        │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  build_content(action_name, action_output, existing_content)         │
│                                                                      │
│  Content-level only. Returns a plain dict, no record wrapper,        │
│  no source_guid, no persistent fields. Just merges action_output     │
│  under action_name into existing_content.                            │
│                                                                      │
│  Used by: utils/content.py wrap_content()                            │
└──────────────────────────────────────────────────────────────────────┘
```

Internal helper `_carry_persistent_fields()` copies tracking + lifecycle fields from `input_record` into the result. Mutable values (lists) are shallow-copied to prevent aliasing — see Caveat 3.

Internal helper `_extract_existing()` pulls the `content` dict from `input_record` so upstream namespaces are preserved when building the new record.

---

## Record State Machine

```
                              ┌─────────┐
                 ┌────────────│  ACTIVE  │────────────┐
                 │            └─────────┘            │
                 │           (processable)           │
                 │                                    │
        ┌────────▼────────┐                  ┌───────▼────────┐
        │   PROCESSED     │                  │  GUARD_SKIPPED  │
        │   (settled,     │                  │  (settled,      │
        │    resettable)  │                  │   resettable)   │
        └─────────────────┘                  └────────────────┘
                 │
        ┌────────▼────────┐                  ┌────────────────┐
        │   COMMITTED     │                  │ GUARD_DEFERRED  │
        │   (settled,     │                  │  (settled,      │
        │    resettable)  │                  │   resettable)   │
        └─────────────────┘                  └────────────────┘

        ┌─────────────────┐   ┌──────────┐   ┌───────────────┐
        │ CASCADE_SKIPPED │   │  FAILED  │   │   EXHAUSTED   │
        │  (settled,      │   │ (settled,│   │  (settled,    │
        │   blocking)     │   │ blocking)│   │   blocking)   │
        └─────────────────┘   └──────────┘   └───────────────┘
```

### Transition Rules

| From | To | Allowed? | Why |
|------|----|----------|-----|
| `None` (new record) | any | Yes | First write — no prior state |
| `ACTIVE` | any settled | Yes | Normal processing progression |
| `PROCESSED`, `COMMITTED`, `GUARD_SKIPPED`, `GUARD_DEFERRED` | `ACTIVE` | Yes | Downstream reset for re-processing |
| any | same state | Yes | Idempotent re-application |
| `CASCADE_SKIPPED`, `FAILED`, `EXHAUSTED` | `ACTIVE` | **No** | Blocking states cannot be reset |
| `CASCADE_SKIPPED`, `FAILED`, `EXHAUSTED` | `CASCADE_SKIPPED` | Yes | Cascade propagation through blocking states |
| settled | different settled | **No** | Cross-settled writes are invalid |

Illegal transitions raise `RecordEnvelopeError`.

---

## State Sets

```python
PROCESSABLE_STATES     = {ACTIVE}
    # Records eligible for LLM/tool processing

SETTLED_STATES         = {all states} - {ACTIVE}
    # Records that have reached a terminal state for this action

RESETTABLE_DOWNSTREAM_STATES = {PROCESSED, COMMITTED, GUARD_SKIPPED, GUARD_DEFERRED}
    # Can be reset to ACTIVE when fed as input to a downstream action

CASCADE_BLOCKING_STATES = {CASCADE_SKIPPED, FAILED, EXHAUSTED}
    # Cannot be reset — downstream actions must cascade-skip these

RETRIABLE_STATES       = {FAILED, EXHAUSTED}
    # The CLI retry command targets records in these states
```

`lifecycle_read.py` uses these sets at load time. When records are loaded from target storage as upstream input, `reset_for_downstream()` transitions resettable records back to `ACTIVE`. Records in blocking states stay as-is for the cascade logic to handle.

---

## transition() Rules and History Entries

`transition()` is the **only sanctioned writer** of `_state`, `_state_history`, and `_state_schema_version`. It mutates the record in-place and returns it for chaining.

Each call appends a history entry:

```python
{
    "timestamp": "2026-06-02T12:34:56.789012+00:00",  # UTC ISO-8601
    "action": "extraction",                             # which action
    "from": "active",                                   # previous state (None for first)
    "to": "processed",                                  # new state
    "reason": "success",                                # why the transition happened
    "detail": None                                      # optional extra context
}
```

History is capped at `STATE_HISTORY_CAP` (64 entries). When overflow occurs, the oldest entries are dropped and the first truncation for each `action_name` in a process emits a `logger.warning` on `agent_actions.record.envelope`; subsequent truncations for the same action are silent. `_state_schema_version` (currently 1) bumps when a required key is added to history entries or an existing key changes semantics.

`can_transition()` is the read-only check — returns `True`/`False` without mutating.

---

## Source GUID Generation

Source GUIDs are **not** generated by the record module — they are assigned upstream by `IDGenerator` (`utils/id_generation/generator.py`) and carried through by `_carry_persistent_fields()`.

```
First-stage records:
    IDGenerator.generate_source_guid() → uuid4()
    Assigned at initial_pipeline.py during staging

Non-first-stage records:
    source_guid comes from upstream action output
    Preserved by RecordEnvelope.build() via _carry_persistent_fields()

Content hashing (separate concept):
    IDGenerator.generate_content_hash(content) → uuid5(NAMESPACE_OID, json)
    Used for deduplication comparison, NOT as source_guid
```

The source_guid is a record's stable identity across pipeline stages. Checkpoint resume depends on this stability — the disposition gate looks up records by source_guid. If a stage overwrites the guid (e.g., generates a fresh uuid4), checkpoint resume breaks because the stored checkpoint references the original guid.

---

## State to Disposition Mapping

`disposition.py` maps lifecycle states to storage dispositions. This is the bridge between the record module and the storage backend.

```
RecordState          →  Disposition
─────────────────────────────────────
PROCESSED            →  SUCCESS
COMMITTED            →  SUCCESS
GUARD_SKIPPED        →  PASSTHROUGH
CASCADE_SKIPPED      →  UNPROCESSED
GUARD_DEFERRED       →  DEFERRED
FAILED               →  FAILED
EXHAUSTED            →  EXHAUSTED
ACTIVE               →  PASSTHROUGH
```

`derive_disposition()` reads `_state` from a record and returns the disposition string value. Raises `RecordEnvelopeError` if `_state` is missing or unrecognized.

---

## TrackedItem for FILE Mode

```python
class TrackedItem(dict):
    __slots__ = ("_source_index",)
```

A `dict` subclass that carries a hidden `_source_index` attribute. Used in FILE mode tool processing:

1. Framework wraps each input item as `TrackedItem(data, source_index=i)` before calling the user's tool function.
2. User code accesses fields normally: `item["question_text"]`.
3. Framework reads `_source_index` after the tool returns to map each output back to its input record.

If user code spreads the item (`{**item}`), `_source_index` is lost because a plain dict is created. The framework detects this and raises `ValueError`.

---

## Lifecycle Validation (lifecycle_read.py)

Records loaded from target storage as upstream input are validated fail-closed:

- `validate_lifecycle()` — single record: requires `_state` present and recognized, `_state_schema_version` supported
- `validate_lifecycle_batch()` — list of records: validates each, fails on first invalid
- `reset_for_downstream()` — resets resettable records to `ACTIVE` via `transition()`

Missing `_state` means the record pre-dates the lifecycle machine or was written outside `transition()`. There is no migration path — the remedy is to delete `agent_io/target/` and re-run.

---

## Reason Constants (reasons.py)

Canonical string constants for every reason that flows through disposition writes, tombstone metadata, `ProcessingResult` factories, or telemetry events. Production code imports from this module instead of using bare string literals.

```
SUCCESS, GUARD_SKIP, GUARD_PREFILTER_SKIP, GUARD_FILTER,
LLM_LAYER_GUARD_SKIP, LLM_LAYER_GUARD_FILTER,
UPSTREAM_UNPROCESSED, PREP_FAILED, BATCH_NOT_RETURNED,
TOOL_MISSING_RECORD, EMPTY_OUTPUT, RETRY_EXHAUSTED,
UNPROCESSED, PARSE_ERROR, GUARD_FILTERED_ALL
```

---

## File Index

| File | Role |
|------|------|
| `envelope.py` | `RecordEnvelope` (build, build_skipped, build_content, transition, can_transition), field category frozensets, `RecordEnvelopeError` |
| `state.py` | `RecordState` enum, state sets (PROCESSABLE, SETTLED, RESETTABLE_DOWNSTREAM, CASCADE_BLOCKING, RETRIABLE), predicate functions |
| `tracking.py` | `TrackedItem` dict subclass with hidden `_source_index` for FILE mode provenance |
| `disposition.py` | `derive_disposition()` — maps `_state` to storage `Disposition` value |
| `lifecycle_read.py` | `validate_lifecycle()`, `validate_lifecycle_batch()`, `reset_for_downstream()` — load-time validation and downstream reset |
| `reasons.py` | Canonical reason string constants for all lifecycle events |
| `__init__.py` | Re-exports: `RecordEnvelope`, `RecordEnvelopeError`, `RecordState`, `TrackedItem`, `RECORD_FRAMEWORK_FIELDS`, `RECORD_LIFECYCLE_FIELDS` |

---

## Caveats

1. **transition() is the only state writer.** Never assign `_state`, `_state_history`, or `_state_schema_version` directly on a record dict. All writes must go through `RecordEnvelope.transition()` to enforce legal edges and maintain the audit trail. Code that bypasses this will produce records that fail `validate_lifecycle()` on reload.

2. **source_guid stability is critical for checkpoint resume.** The disposition gate looks up records by source_guid to determine what has already been processed. If any stage overwrites or regenerates the guid, checkpoint resume silently reprocesses records or skips them entirely. `_carry_persistent_fields()` preserves it; `TaskPreparer._normalize_input()` preserves it. Do not break this chain.

3. **_state_history is shallow-copied to prevent aliasing.** `_carry_persistent_fields()` does `list(value)` on the history list. Without this, input and output records share the same list object, and `transition()` (which appends in-place) would corrupt the input record's audit trail. The copy is shallow — the inner entry dicts are shared — which is safe because entries are never mutated after creation.

4. **TrackedItem spread drops provenance.** If user tool code does `new_dict = {**tracked_item}`, the result is a plain dict without `_source_index`. The framework checks for this after tool execution and raises `ValueError`. This is a deliberate fail-loud contract, not a bug.

5. **build() stores action_output by reference.** The content dict contains a direct reference to the `action_output` dict passed in. Callers must not mutate `action_output` after calling `build()` or the record's content will change silently.

6. **_state is a stage field, not a lifecycle field.** It lives in `RECORD_STAGE_FIELDS`, not `RECORD_LIFECYCLE_FIELDS`. This means `_carry_persistent_fields()` does NOT carry `_state` from input to output. Each stage must call `transition()` to set the state explicitly. The *history* is carried; the *current value* is not.

7. **History cap drops oldest entries.** When `_state_history` exceeds 64 entries, the list is trimmed to the most recent 64. For records that pass through many actions or retry loops, early history entries may be lost. The cap prevents unbounded growth in storage. The first truncation for each `action_name` in a process emits a `logger.warning`; subsequent truncations for the same action are silent (once-per-action-per-process dedup keyed on `action_name` because records do not carry run/workflow identifiers).

8. **No migration path for missing _state.** `validate_lifecycle()` is fail-closed. Records without `_state` (pre-dating the lifecycle machine or written by external tools) cannot be migrated. The only remedy is `rm -rf agent_io/target/` and re-run from scratch.

9. **derive_disposition() covers all states including ACTIVE.** ACTIVE maps to PASSTHROUGH, not to an error. This handles the edge case where a record is written to storage before processing completes (e.g., during incremental checkpointing).

10. **CASCADE_SKIPPED can transition to CASCADE_SKIPPED.** Blocking states cannot be reset to ACTIVE, but `_is_legal_transition()` allows a cascade-blocking state to transition to `CASCADE_SKIPPED`. This enables cascade propagation: if an upstream record is FAILED, the downstream record becomes CASCADE_SKIPPED, and that cascade can continue further downstream.

11. **reason constants must be used in production code.** `reasons.py` exists so that disposition writes, tombstone metadata, and telemetry events use consistent strings. Bare string literals for these values are a bug — they silently diverge from the canonical set and break downstream filtering or reporting.

---
title: Record Lifecycle
sidebar_position: 1
---

# Record Lifecycle

Every record flowing through an Agent Actions workflow carries metadata that tracks its progress through the pipeline. This page documents the `_state` field, the `_state_history` array, and the disposition system.

## The `_state` Field

Every record has a `_state` field governed by a finite state machine. There are **6 producible states**:

| State | Category | Behavior |
|-------|----------|----------|
| `active` | Processable | Ready for the next action |
| `processed` | Resettable | Reset to `active` at the next action boundary |
| `guard_skipped` | Resettable | Reset to `active` at the next action boundary |
| `cascade_skipped` | Terminal | Record stops flowing — upstream dependency failed |
| `failed` | Terminal | Record hit an unrecoverable error |
| `exhausted` | Terminal | Record exhausted all repair iterations |

> **Note:** `committed` and `guard_deferred` were **removed** from the `RecordState` enum in VIOL-0029/0030. They had zero stamp sites — no code path ever wrote them — so the state machine now produces only the six states above. A record carrying either value fails loudly (`RecordEnvelopeError`) on load.

Three categories:

| Category | States | Behavior |
|----------|--------|----------|
| **Processable** | `active` | Ready for the next action |
| **Resettable** | `processed`, `guard_skipped` | Reset to `active` at the next action boundary |
| **Terminal** | `cascade_skipped`, `failed`, `exhausted` | Record stops flowing. No further actions process it. |

## The `_state_history` Array

Each state transition appends to `_state_history`:

```json
{
  "_state": "processed",
  "_state_history": [
    { "action": "classify_ticket", "from": "active", "to": "processed", "reason": "success" }
  ]
}
```

### History Capping

The `_state_history` array is capped at **64 entries** (`STATE_HISTORY_CAP` in `agent_actions/record/envelope.py`). In workflows with roughly 16 or more actions, histories can reach this limit and the oldest entries are dropped. The framework emits an INFO log the first time this happens for a given action in a process:

```
_state_history capped at 64 entries; dropped N oldest transition(s) for action='<name>'.
```

The log fires at most once per action per process to avoid per-record spam. It is written to `events.json` at WARNING but kept off the terminal, since the cap is a framework constant rather than anything you configure; run with `-v` to see it there. When it appears, `_state_history` for that action has already lost its oldest transitions.

## Dispositions

The `record_disposition` table records, per action and record, **what happened** (the
`disposition` column) and **why** (the `reason` column). There is no `reason_class`
column.

### `disposition` column

A fixed enum derived from the record's final `_state` (see `Disposition` in
`agent_actions/storage/backend.py`):

| Disposition | Meaning |
|-------------|---------|
| `success` | Action completed successfully |
| `passthrough` | Answered with nothing, kept as a tombstone (`on_empty: skip`) |
| `skipped` | WHERE clause excluded the record from this action |
| `filtered` | Guard condition was false; record excluded from output |
| `unprocessed` | Not answered: a dependency didn't produce output (cascade casualty), or a guard skipped it |
| `deferred` | In-flight HITL/batch awaiting resolution |
| `exhausted` | All repair iterations failed |
| `failed` | Unrecoverable error |

### `reason` column

A free-form canonical reason string giving the specific cause (see
`agent_actions/record/reasons.py`). Common values include `success`, `guard_filter`,
`guard_skip`, `guard_prefilter_skip`, `upstream_unprocessed`, `tool_missing_record`,
`prep_failed`, `empty_output`, `parse_error`, `retry_exhausted`,
`expectations_exhausted`, `consumed_into_output`, and `batch_not_returned` (a `failed`
record a batch provider left out of its results, which no retry will send again).

> **Note:** `upstream_unprocessed` and `tool_missing_record` are `reason` strings, not
> `disposition` values — the matching disposition for both is `unprocessed`. Query the
> `disposition` column for the outcome category and the `reason` column for the specific
> cause. A guard skip is `unprocessed` too in both run modes, with reason `guard_skip`, or
> `guard_prefilter_skip` for an action of `granularity: file`, so the guard judges the
> record again on the next run.

### The cause on an `upstream_unprocessed` tombstone

The row an action stores for a record an action above it failed, exhausted or skipped
names what blocked it, in its `metadata`:

```json
"metadata": {
  "reason": "upstream_unprocessed",
  "agent_type": "tombstone",
  "upstream_action": "summarize",
  "upstream_state": "failed",
  "upstream_reason": "the model failed page alpha"
}
```

`upstream_action` is the first action that blocked the record, not the one directly
above: every action below it repeats the same cause. `upstream_state` is the state that
action left the record in (`failed`, `exhausted` or `cascade_skipped`, the last for a
record it did not answer for a reason of its own, such as `batch_not_returned`), and
`upstream_reason` is that action's reason. Below a fan-in, it names the branch that
blocked the merged record. When nothing on the record names the action, only
`upstream_state` is there.

## Version Correlation

When using `version_consumption: merge`, records are correlated via `version_correlation_id`, `root_target_id`, and `parent_target_id`. On root records (records with no parent), `parent_target_id` is **absent** from the JSON object — not `null`. Always use a presence check (`"parent_target_id" in record`) rather than a null check.

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
| `exhausted` | Terminal | Record exhausted all reprompt attempts |

> **Note:** `committed` and `guard_deferred` appear in the `RecordState` enum but have **zero stamp sites** in the framework — no code path writes them. They are dead states and should not be relied upon. See VIOL-0029/0030.

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

The log fires at most once per action per process to avoid per-record spam. If you see it, `_state_history` for that action has already lost its oldest transitions.

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
| `passthrough` | Record passed through unprocessed (e.g. guard skip, still active) |
| `skipped` | WHERE clause excluded the record from this action |
| `filtered` | Guard condition was false; record excluded from output |
| `unprocessed` | A dependency didn't produce output (cascade casualty) |
| `deferred` | In-flight HITL/batch awaiting resolution |
| `exhausted` | All reprompt attempts failed |
| `failed` | Unrecoverable error |

### `reason` column

A free-form canonical reason string giving the specific cause (see
`agent_actions/record/reasons.py`). Common values include `success`, `guard_filter`,
`guard_skip`, `guard_prefilter_skip`, `upstream_unprocessed`, `tool_missing_record`,
`prep_failed`, `empty_output`, `parse_error`, `retry_exhausted`, and
`reprompt_exhausted`.

> **Note:** `upstream_unprocessed` and `tool_missing_record` are `reason` strings, not
> `disposition` values — the matching disposition for both is `unprocessed`. Query the
> `disposition` column for the outcome category and the `reason` column for the specific
> cause.

## Version Correlation

When using `version_consumption: merge`, records are correlated via `version_correlation_id`, `root_target_id`, and `parent_target_id`. On root records (records with no parent), `parent_target_id` is **absent** from the JSON object — not `null`. Always use a presence check (`"parent_target_id" in record`) rather than a null check.

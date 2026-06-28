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

The `_state_history` array is capped at **64 entries**. In workflows with many actions (16+), histories near this limit will have their oldest entries silently truncated. The truncation is silent — no log message is emitted, so do not rely on `_state_history` containing the full transition record for very long workflows.

For most workflows (under ~16 actions with standard retries), this cap will never be reached.

## Dispositions

Each record also has a `reason_class` in the disposition table that explains *why* it reached its current state:

| Reason class | Meaning |
|-------------|---------|
| `success` | Action completed successfully |
| `filtered` | Guard condition was false; record excluded from output |
| `skipped` | WHERE clause or guard skip; record preserved but not processed |
| `upstream_unprocessed` | A dependency didn't produce output for this record |
| `tool_missing_record` | A tool action didn't emit output for this record |
| `exhausted` | All reprompt attempts failed |
| `failed` | Unrecoverable error |

## Version Correlation

When using `version_consumption: merge`, records are correlated via `version_correlation_id`, `root_target_id`, and `parent_target_id`. On root records (records with no parent), `parent_target_id` is **absent** from the JSON object — not `null`. Always use a presence check (`"parent_target_id" in record`) rather than a null check.

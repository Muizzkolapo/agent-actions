---
title: Record Lifecycle
sidebar_position: 1
---

# Record Lifecycle

Each record in an Agent Actions workflow carries metadata. The metadata tracks the progress of the record through the workflow. This page describes the `_state` field, the `_state_history` array and the disposition system.

## The `_state` Field

Each record has a `_state` field. A finite state machine controls the value of this field. The state machine can produce **6 states**:

| State | Category | Behavior |
|-------|----------|----------|
| `active` | Processable | The record is ready for the next action. |
| `processed` | Resettable | The framework resets the state to `active` at the next action boundary. |
| `guard_skipped` | Resettable | The framework resets the state to `active` at the next action boundary. |
| `cascade_skipped` | Terminal | The record stops. An upstream dependency failed. |
| `failed` | Terminal | The record had an unrecoverable error. |
| `exhausted` | Terminal | The record used all the repair iterations. |

:::note
`committed` and `guard_deferred` are not members of `RecordState`. Thus the state machine produces only the six states above. A record in target storage can carry any other `_state` value. When a downstream action loads that record, the framework rejects it. The error is a `ConfigurationError` (`Record has unrecognised '_state' value ...`).
:::

The states are in three categories:

| Category | States | Behavior |
|----------|--------|----------|
| **Processable** | `active` | The record is ready for the next action. |
| **Resettable** | `processed`, `guard_skipped` | The framework resets the state to `active` at the next action boundary. |
| **Terminal** | `cascade_skipped`, `failed`, `exhausted` | The record stops. No downstream action processes it. |

## The `_state_history` Array

Each state transition adds an entry to `_state_history`:

```json
{
  "_state": "processed",
  "_state_history": [
    { "timestamp": "2026-11-03T18:57:45.711349+00:00", "action": "classify_ticket", "from": null, "to": "processed", "reason": "success", "detail": null }
  ]
}
```

When the action stamps the record for the first time, `from` is `null`. Each entry also has a `timestamp` and a `detail`. At the next action boundary, the framework adds a second entry. This entry resets a `processed` or `guard_skipped` record to `active`, with the reason `downstream_reset`.

### History Capping

The `_state_history` array holds a maximum of **64 entries** (`STATE_HISTORY_CAP` in `agent_actions/record/envelope.py`). In a workflow with approximately 16 or more actions, a history can reach this limit. Then the framework removes the oldest entries. The first time that this occurs for an action in a process, the framework writes a WARNING log:

```
_state_history capped at 64 entries; dropped N oldest transition(s) for action='<name>'. Fires at most once per action per process.
```

The framework writes the log a maximum of one time for each action in each process. This limit prevents one log for each record. The framework writes the log to `events.json`, but not to the terminal. The reason is that the cap is a framework constant, not a value that you configure. To see the log on the terminal, run with `-v`. When the log appears, the `_state_history` of that action has already lost its oldest transitions.

## Dispositions

The `record_disposition` table records **what happened** (the `disposition` column) and
**why** (the `reason` column), for each action and record. The table has no `reason_class`
column.

### `disposition` column

The `disposition` column holds one of eight fixed enum values (see `Disposition` in
`agent_actions/storage/backend.py`). Most of the values come from the final `_state` of the record:

| Disposition | Meaning |
|-------------|---------|
| `success` | The action completed successfully. |
| `passthrough` | The action answered with nothing. The framework keeps the record as a tombstone (`on_empty: skip`). |
| `skipped` | A WHERE clause excluded the record from this action. |
| `filtered` | The guard condition was false. The record is excluded from the output. In a batch run, the framework writes this disposition when it submits the batch, because it sends nothing for the record. |
| `unprocessed` | The action did not answer the record. A dependency did not produce output (cascade casualty), or a guard skipped the record. |
| `deferred` | A HITL or batch record is in flight and waits for resolution. A batch record can stay `deferred` after its batch is collected, if the store refused its outcome. The next `agac run` or `agac retry` gives that record the outcome that its stored row represents. |
| `exhausted` | All repair iterations failed. |
| `failed` | An unrecoverable error occurred. In an online run, if the store refuses to record a `failed` or `exhausted` disposition, the action fails with the store error. Thus `agac retry` still reaches the record. |

### `reason` column

The `reason` column holds a free-form canonical reason string. The string gives the specific
cause (see `agent_actions/record/reasons.py`). Common values include:

- `success`
- `guard_filter`
- `guard_skip`
- `guard_prefilter_skip`
- `upstream_unprocessed`
- `tool_missing_record`
- `prep_failed`
- `empty_output`
- `parse_error`
- `retry_exhausted`
- `expectations_exhausted`
- `expectations_failed`: A `success` record that shipped with a failing
  [expectations](../validation/expectations.md) verdict under `on_exhausted: return_last` or
  `repair: none`. The record is still a success, so it blocks no downstream action.
- `consumed_into_output`
- `consumed_into_another_record`: An `unprocessed` record at a fan-in. The `granularity: File`
  tool of one branch folded this record into the row of another record.
- `batch_not_returned`: A `failed` record that a batch provider omitted from its results. No
  retry sends this record again.

Query the `disposition` column for the outcome category. Query the `reason` column for the
specific cause.

:::note
`upstream_unprocessed` and `tool_missing_record` are `reason` strings, not `disposition`
values. The matching disposition for the two strings is `unprocessed`. A guard skip is also
`unprocessed` in the two run modes. Its reason is `guard_skip`, or `guard_prefilter_skip` for
an action of `granularity: file`. Thus the guard examines the record again on the next run.
:::

### The cause on an `upstream_unprocessed` tombstone

If an upstream action failed, exhausted or skipped a record, an action stores a row for that
record. The `metadata` of this row names the cause of the block:

```json
"metadata": {
  "reason": "upstream_unprocessed",
  "agent_type": "tombstone",
  "upstream_action": "summarize",
  "upstream_state": "failed",
  "upstream_reason": "the model failed page alpha"
}
```

`upstream_action` is the first action that blocked the record. It is not the action directly
upstream. Each action downstream of the first action repeats the same cause.

`upstream_state` is the state in which that action left the record: `failed`, `exhausted` or
`cascade_skipped`. The state is `cascade_skipped` when the action did not answer the record for
a reason of its own, for example `batch_not_returned`. `upstream_reason` is the reason of that
action.

Downstream of a fan-in, the metadata names the branch that blocked the merged record. If no
data on the record names the action, only `upstream_state` is present.

One branch of a fan-in can fold a record into the row of another record. The tombstone of the
fan-in for that record has these fields:

- The reason `consumed_into_another_record`.
- `upstream_action`, which names the `granularity: File` tool that folded the record.
- `upstream_reason: consumed_into_output`.
- `consumed_into`, which is the `source_guid` of the row that received the record.

This tombstone has no `upstream_state`, because the tool answered the record. The actions
downstream of the fan-in skip the record as `upstream_unprocessed`, and they name the same
cause. A version merge (`version_consumption`) leaves the same tombstone in one case. One
version of a versioned `granularity: File` tool folded a record into the row of another record,
and another version kept the record.

## Version Correlation

With `version_consumption: merge`, the framework correlates records with `version_correlation_id`, `root_target_id` and `parent_target_id`. On a root record (a record with no parent), `parent_target_id` is **absent** from the JSON object. Its value is not `null`. Always use a presence check (`"parent_target_id" in record`), not a null check.

All versions of a source record carry the same `version_correlation_id`. The framework derives this id from the name of the workflow and from the record. Thus a version that is answered again later, from a different checkout, worktree or mount, still merges with the versions that it kept. In an agac release before this one, the stored ids also included the project path. If a merge finds a record whose versions carry different ids, the merge writes a warning that names the record. The merge then holds that record in parts, and each part is missing a version. To answer all versions under one id, run `agac run --rerun <version base>` (`--rerun vote` for `vote_1` … `vote_N`).

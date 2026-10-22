---
title: Run Modes
sidebar_position: 4
---

# Run Modes

Agent Actions supports two execution modes: **online** (real-time) and **batch** (cost-optimized).

## Overview

| Mode | Processing | Latency | Cost | Use Case |
|------|------------|---------|------|----------|
| **online** | Synchronous | Real-time | Standard | Interactive, development |
| **batch** | Asynchronous | Hours | Up to 50% savings | Production, large datasets |

## Configuration

```yaml
defaults:
  run_mode: batch  # or "online"

actions:
  - name: my_action
    run_mode: online  # Override per-action
```

:::info
`run_mode` accepts the string values `batch` and `online` (case-insensitive). These map to the `RunMode` enum internally.
:::

## Online Mode

Requests process synchronously with immediate responses.

```yaml
defaults:
  run_mode: online
```

**When to use:**
- Development and testing
- Interactive applications
- Small datasets (< 100 records)
- Debugging workflows

## Batch Mode

Requests queue for asynchronous batch processing with significant cost savings.

```yaml
defaults:
  run_mode: batch
```

**When to use:**
- Production workloads
- Large datasets (100+ records)
- Cost-sensitive processing
- Scheduled/overnight jobs

### Provider Support

| Provider | Batch API | Cost Savings |
|----------|-----------|--------------|
| OpenAI | Yes, except an action with `base_url` | ~50% |
| Anthropic | Yes | ~50% |
| Google Gemini | Yes | Varies |
| Groq | Yes | Varies |
| Ollama | Yes (local) | N/A |

### When the provider refuses a batch

Each input file is sent as its own batch. If the provider refuses one (a quota, a network
error, a request it rejects), the run fails the action once every file has been walked,
even when the batches of its other files were taken. Run again: the records of the refused
file that have no answer yet are sent again. The records the action had already answered,
in that file or any other, are kept while its config is unchanged, and a batch still out
for another file is kept and collected rather than sent again.

A run collects batches only after a run that got every file sent, so while the provider
refuses a file, the batches already out for the others wait; the run names them.
A refusal that persists, such as a request the provider rejects every time, holds them
for as long as it lasts, and a provider keeps results only for a limited time. Fix the file
the error names, or take it out of the input, and run again.

### When the provider cannot be reached while collecting

A run asks the provider about each finished batch before reading its results. If it cannot
reach the provider about one (the call cannot connect, times out, or gets a server error),
it reads the others, leaves that batch where it is, and pauses as it does while a batch is
still out, naming the file it could not read. Run again to collect it: nothing is sent
again, and the files already read are not read again. A run that cannot reach the provider
while checking whether its batches have finished pauses the same way. It keeps pausing for
as long as the provider cannot be asked; to give up on those batches instead,
`agac run --fresh` sends every record of the workflow again.

### When the provider leaves a record out

A batch can come back finished with a record missing from its results. An action whose
retry is on (see [Retry](./retry)) sends that record again in a retry batch
([Batch Recovery](./batch-recovery)). With retry off, or once nothing will send it again,
the record is failed with the reason `batch_not_returned`: the action completes with
failures, the actions that read it skip the record, and `agac retry` sends it again.

### When the provider ends a batch without results

agac reads nothing from a batch the provider failed or cancelled before it finished, in this
run or any later one. Nor from one that ran out of the provider's time window (OpenAI's and
Groq's `expired`, Gemini's `JOB_STATE_EXPIRED`), or one the provider answers about but no
longer reports finished, such as one it now reports failed or expired. The run reads the
other files, names the file and its batch, marks the records of that file failed, and
completes the action with those failures, for `agac retry` to send again. That sends every
record of the file again, including those an expired OpenAI or Groq batch had already
answered: the provider keeps those answers, but agac does not read them. A run that cannot
mark those records, because the store could not be read, pauses as for a batch still out,
and the next run marks them. When the provider ended every file's batch this way, the run
fails the action instead, and the next run sends every file again.

A batch the provider is still cancelling has not ended: the run pauses as for a batch still
out, and a later run, once the provider reports it cancelled, marks its records failed as
above. An Anthropic batch canceled while it ran ends with a result for every request, and
the run reads it like any other.

### When the provider reports a status agac does not know

agac maps each provider's batch statuses onto its own. A status no mapping knows, such as
one a provider adds later, is taken as still running: the run pauses, naming the batch and
the status, and each run after it asks the provider again until it reports one agac knows.

### When a file's input changes while its batch is out

A batch answers the records it was sent. If a record leaves a file's input while that
file's batch is out, for example by being removed from staging, a run that resumes the
action after a collect pass stopped partway, or after a run checking on the batch was
interrupted, reads the input again and leaves that record's answer out of the file, as
online does. A file that every record has left waits for its batch like any other and is
then stored empty. A run that only collects does not read the input again, so it still
writes a departed record's answer into the file.

In every case the provider has already answered the records it was sent: once a batch is
out, its answers are paid for whether they are kept or not.

### Batch Commands

```bash
# Check batch status
agac batch status --batch-id batch_abc123

# Retrieve completed results
agac batch retrieve --batch-id batch_abc123

# Retry failed records
agac retry -a my_workflow
```

See [batch Commands](../cli/batch) for complete CLI reference.

Failed records of a batch action are retried with the top-level
[`retry`](../cli/retry) command, as they are for an online one. The retry
submits a batch holding only the records it names, and the next run collects
it. While a batch is still out at the provider the retry is refused: run the
workflow again to collect it first, and pass `--abandon-in-flight` only when
the provider no longer has it. See
[Retrying an action that runs in batch mode](../cli/retry#retrying-an-action-that-runs-in-batch-mode).

## Mixing Modes

Override at the action level for hybrid workflows:

```yaml
defaults:
  run_mode: batch

actions:
  - name: bulk_extraction
    # Uses default batch mode

  - name: interactive_validation
    run_mode: online  # Override for this action
```

### Switching an interrupted online action to batch

An online run stopped partway through a file keeps the records it finished as checkpoint
rows until the file is written. If the action is then switched to `run_mode: batch`, the
batch run sends those records again with the rest of the file, so each is answered, and paid
for, a second time. Resumed online instead, the action keeps those answers and sends only
the records it had not finished.

This holds when an earlier run stored the file too, as when the action was edited after it
completed and the run after the edit was stopped: resumed online, each record that run
answered keeps that answer in place of the row stored before the edit; switched to batch,
it is sent again. The row stored before the edit is kept for neither.

## See Also

- [batch Commands](../cli/batch) - CLI reference for batch operations
- [retry Command](../cli/retry) - Retry failed records, in either run mode
- [Batch Recovery](./batch-recovery) - Two-phase retry and repair for batch processing
- [Context Handling](./context-handling) - Batch vs online context differences
- [Granularity](./granularity) - Record vs file processing

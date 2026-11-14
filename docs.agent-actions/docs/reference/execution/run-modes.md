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

:::note
`run_mode` accepts the string values `batch` and `online` (case-insensitive). These values map to the `RunMode` enum internally.
:::

:::note
Tool actions and human-in-the-loop (HITL) actions always run online, also in a batch workflow. For these actions, Agent Actions accepts a `run_mode: batch` from `defaults:` or on the action, and shows no message. Agent Actions stages, runs and reports these actions as online actions.
:::

## Online Mode

Online mode processes requests synchronously, with immediate responses. An LLM action sends one record at a time, unless the action sets [`record_concurrency`](../configuration/index.md#record-concurrency).

```yaml
defaults:
  run_mode: online
```

**When to use:**
- Development and testing
- Interactive applications
- Small datasets (fewer than 100 records)
- Debugging workflows

## Batch Mode

Batch mode puts requests in a queue for asynchronous batch processing, with significant cost savings.

```yaml
defaults:
  run_mode: batch
```

**When to use:**
- Production workloads
- Large datasets (100+ records)
- Cost-sensitive processing
- Scheduled jobs and overnight jobs

### Provider Support

| Provider | Batch API | Cost Savings |
|----------|-----------|--------------|
| OpenAI | Yes, except an action with `base_url` | ~50% |
| Anthropic | Yes | ~50% |
| Google Gemini | Yes | Varies |
| Groq | Yes | Varies |
| Ollama | Yes (local) | N/A |

### When the provider refuses a batch

Agent Actions sends each input file as a separate batch. The provider can refuse a batch (a
quota, a network error, a request that the provider rejects). If the provider refuses a batch,
the run fails the action after the run walks all files. The run fails the action even when the
provider took the batches of the other files of the action.

Run the workflow again. The next run sends again the records of the refused file that have no
answer yet. The run keeps the records that the action already answered, in that file or in any
other file. The run keeps a batch that is still at the provider for another file. The run
collects that batch, and does not send it again.

A run collects batches only after a run that sent all files. Thus, while the provider refuses
a file, the batches that are already at the provider for the other files wait. The run names
these batches. A refusal that continues holds these batches for as long as the refusal
continues. An example is a request that the provider rejects each time. A provider keeps results
only for a limited time. Fix the file that the error names, or remove the file from the input.
Then run the workflow again.

### When the provider cannot be reached while collecting

Before a run reads the results of a finished batch, the run asks the provider about the batch.
The run cannot reach the provider if the call cannot connect, times out, or gets a server error.
If the run cannot reach the provider about one batch, the run reads the other batches. The run does not change that
batch. Then the run pauses, as it does while a batch is still at the provider. The run names the
file that it could not read.

To collect the batch, run the workflow again. The next run sends nothing again. The next run does
not read again the files that a run already read.

A run that cannot reach the provider while it checks whether its batches have finished pauses
in the same way. The run continues to pause for as long as the provider cannot be
asked. To abandon those batches, use `agac run --fresh`. This command sends each record of the
workflow again.

### When the provider omits a record {/* #when-the-provider-leaves-a-record-out */}

A batch can come back finished, with a record missing from its results. If retry is enabled
(see [Retry](./retry)), the action sends that record again in a retry batch
([Batch Recovery](./batch-recovery)). If retry is disabled, or if nothing will send the record
again, the record fails with the reason `batch_not_returned`. The action completes with
failures, and the downstream actions skip the record. `agac retry` sends the record again.

### When the provider ends a batch without results

agac reads nothing from these batches, in this run or in any later run:

- A batch that the provider failed or cancelled before the batch finished.
- A batch that used all of the time window of the provider (`expired` for OpenAI and Groq,
  `JOB_STATE_EXPIRED` for Gemini).
- A batch that the provider answers about but no longer reports as finished. An example is a
  batch that the provider now reports as failed or expired.

For such a batch, the run reads the other files and names the file and its batch. The run marks
the records of that file as failed. The run completes the action with those failures, so that
`agac retry` can send the records again. `agac retry` sends each record of the file again. These
records include the records that an expired OpenAI or Groq batch already answered. The provider
keeps those answers, but agac does not read them.

If the run cannot read the store, the run cannot mark those records. In this case, the run
pauses as for a batch that is still at the provider. The next run marks the records. If the
provider ended the batch of each file in this way, the run fails the action instead. The next
run sends each file again.

A batch that the provider is still cancelling has not ended. The run pauses as for a batch that
is still at the provider. After the provider reports the batch as cancelled, a later run marks
its records as failed, as described above. An Anthropic batch that was canceled while it ran ends
with a result for each request. The run reads that batch like any other batch.

### When the provider reports a status agac does not know

agac maps the batch statuses of each provider to its own statuses. agac treats a status that no
mapping knows as still running. An example is a status that a provider adds later. The run
pauses and names the batch and the status. Each later run asks the provider again, until the
provider reports a status that agac knows.

### When a file's input changes while its batch is out

A batch answers the records that it got. A record can leave the input of a file while the batch
of that file is at the provider. For example, you remove the record from staging. A run that
resumes the action reads the input again in two cases. The first case is after a collect pass
stopped partway. The second case is after a run that checked on the batch was interrupted. That run does not write the answer of the
departed record into the file, as online mode does.

A file that all its records left waits for its batch like any other file. Then the system stores
the file empty. A run that only collects does not read the input again. Thus that run still
writes the answer of a departed record into the file.

In each case, the provider has already answered the records that it got. After a batch is at
the provider, you pay for its answers, whether the run keeps them or not.

### Batch Commands

```bash
# Check batch status
agac batch status --batch-id batch_abc123

# Retrieve completed results
agac batch retrieve --batch-id batch_abc123

# Retry failed records
agac retry -a my_workflow
```

For the complete CLI reference, see [batch Commands](../cli/batch).

The top-level [`retry`](../cli/retry) command retries the failed records of a
batch action, as it does for an online action. The retry submits a batch that
holds only the records that it names. The next run collects that batch. While a
batch is still at the provider, the retry command refuses the retry. Run the
workflow again to collect the batch first. Pass `--abandon-in-flight` only when
the provider no longer has the batch. See
[Retrying an action that runs in batch mode](../cli/retry#retrying-an-action-that-runs-in-batch-mode).

## Mixing Modes

For a hybrid workflow, override the mode at the action level:

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

If an online run stops partway through a file, the run keeps the finished records as checkpoint
rows. The run keeps these rows until the file is written. If you then set `run_mode: batch`,
the batch run sends those records again with the rest of the file. Thus the provider answers
each record a second time, and you pay for each record a second time. If you resume the action
online, the action keeps those answers. The action sends only the records that it did not
finish.

The same rule applies when an earlier run also stored the file. For example,
`agac run --rerun` answered a completed action again, and that run was stopped. If you resume
the action online, each record that the rerun answered keeps that answer. That answer takes the
place of the row stored before it. If you change the action to batch, the batch run sends each of these records
again. Neither the online resume nor the batch run keeps the row stored before the rerun.

## See Also

- [batch Commands](../cli/batch) - CLI reference for batch operations
- [retry Command](../cli/retry) - Retry failed records, in the two run modes
- [Batch Recovery](./batch-recovery) - Two-phase retry and repair for batch processing
- [Context Handling](./context-handling) - Prompt context in the two run modes
- [Granularity](./granularity) - Record processing and file processing

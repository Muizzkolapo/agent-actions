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
| OpenAI | Yes | ~50% |
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

A batch the provider answers about but no longer reports finished, such as one it now
reports failed or expired, cannot be read by a later run either. The run reads the other
files and marks the records of that batch's file failed, for `agac retry` to send again.

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

## See Also

- [batch Commands](../cli/batch) - CLI reference for batch operations
- [retry Command](../cli/retry) - Retry failed records, in either run mode
- [Batch Recovery](./batch-recovery) - Two-phase retry and repair for batch processing
- [Context Handling](./context-handling) - Batch vs online context differences
- [Granularity](./granularity) - Record vs file processing

---
title: Execution
sidebar_position: 1
---

# Execution

The execution layer runs the LLM calls and the data transformations, and it makes the validated outputs. Your workflow configuration controls the execution layer.

## Core Configuration

| Setting | Purpose | Options |
|---------|---------|---------|
| `run_mode` | The processing strategy | `online` (real-time), `batch` (lower cost) |
| `granularity` | The processing scope | `record` (one record at a time), `file` (all records together) |
| `guard` | Conditional execution | Skip or filter, based on the data |
| `retry` | Error handling | Automatic retry for transient failures |
| `versions` | Parallel variations | Many iterations with different parameters |

## Quick Reference

| Need | Configuration |
|------|---------------|
| Lower costs, and you can wait for the results | `run_mode: batch` |
| Immediate responses | `run_mode: online` |
| A transformation for each record | `granularity: record` |
| Aggregation or exports | `granularity: file` |
| Conditional execution | `guard: { condition: "...", on_false: filter }` |
| Transient failures | `retry: { max_attempts: 3, on_exhausted: return_last }` |

## Schema Analysis

To analyze the workflow schemas and the field dependencies before you make API calls, run this command:

```bash
agac schema -a my_workflow
```

The command shows the input schema and the output schema of each action. It helps you find field reference errors.

## See Also

- [Run Modes](./run-modes.md) — Batch execution and online execution
- [Granularity](./granularity.md) — Record processing and file processing
- [Guards](./guards.md) — Conditional execution of an action
- [Retry](./retry.md) — Automatic error handling
- [Version Actions](./versions.md) — Parallel processing with iterations
- [Context Handling](./context-handling.md) — The data flow between actions

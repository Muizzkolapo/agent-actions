---
title: Execution
sidebar_position: 1
---

# Execution

The execution layer orchestrates LLM calls, data transformations, and validated outputs based on your workflow configuration.

## Core Configuration

| Setting | Purpose | Options |
|---------|---------|---------|
| `run_mode` | Processing strategy | `online` (real-time), `batch` (cost-optimized) |
| `granularity` | Processing scope | `record` (per-item), `file` (all items) |
| `guard` | Conditional execution | Skip or filter based on data |
| `retry` | Error handling | Automatic retry for transient failures |
| `versions` | Parallel variations | Multiple iterations with different parameters |

## Quick Reference

| Need | Configuration |
|------|---------------|
| Lower costs, can wait 24h | `run_mode: batch` |
| Immediate responses | `run_mode: online` |
| Per-item transformations | `granularity: record` |
| Aggregation/exports | `granularity: file` |
| Conditional execution | `guard: { condition: "...", on_false: filter }` |
| Handle transient failures | `retry: { max_attempts: 3, on_exhausted: return_last }` |

## Schema Analysis

Analyze workflow schemas and field dependencies before making API calls:

```bash
agac schema -a my_workflow
```

Shows input/output schemas for each action and helps catch field reference errors.

## See Also

- [Run Modes](./run-modes.md) — Batch vs online execution
- [Granularity](./granularity.md) — Record vs file processing
- [Guards](./guards.md) — Conditional action execution
- [Retry](./retry.md) — Automatic error handling
- [Version Actions](./versions.md) — Parallel processing with iterations
- [Context Handling](./context-handling.md) — Data flow between actions

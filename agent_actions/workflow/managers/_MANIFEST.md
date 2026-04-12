# Workflow Managers Manifest

## Overview

Tracks workflow artifacts, batching, loops, state, and skip logic used by the runner.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch.py` | Module | Batch helpers that coordinate chunked execution. | `llm.batch`, `processing` |
| `loop.py` | Module | VersionOutputCorrelator — version output correlation for parallel map-reduce patterns. | `workflow`, `validation` |
| `manifest.py` | Module | Generates workflow manifests consumed by tooling/docs. | `tooling.docs`, `workflow` |
| `output.py` | Module | `ActionOutputManager`: loads upstream outputs, resolves version correlation, creates passthrough outputs. `detect_explicit_version_consumption()` result is lazy-cached per instance to avoid redundant computation. | `output`, `workflow` |
| `skip.py` | Module | Skip logic used when upstream items fail or guard conditions filter them. | `validation`, `workflow` |
| `state.py` | Module | `ActionStatus(str, Enum)` — typed action lifecycle statuses (`PENDING`, `RUNNING`, `BATCH_SUBMITTED`, `CHECKING_BATCH`, `COMPLETED`, `COMPLETED_WITH_FAILURES`, `FAILED`, `SKIPPED`). `COMPLETED_STATUSES` and `TERMINAL_STATUSES` frozensets derived from enum. `ActionStateManager` — manages action execution state persistence and queries. Key methods: `is_failed()`, `is_skipped()`, `is_terminal()`, `is_in_progress()`, `get_pending_actions()`, `get_skipped_actions()`, `is_workflow_done()`, `get_summary()`. | `workflow`, `state_management` |

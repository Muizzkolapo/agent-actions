# Workflow Managers Manifest

## Overview

Tracks workflow artifacts, batching, loops, state, and skip logic used by the runner.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch.py` | Module | Batch helpers that coordinate chunked execution. | `llm.batch`, `processing` |
| `loop.py` | Module | `VersionOutputCorrelator` — version output correlation for parallel map-reduce patterns. `prepare_correlated_input` returns the correlated directory, raises `AllVersionsFilteredError` when every version source produced zero records (executor cascade-skips), or `ConfigurationError` on a correlation/storage fault. A source that vanishes between listing and reading, and a correlated file whose store write fails, are both skipped rather than raised — each marks the consumer's record count unknown, since its correlated input is assembled before its own walk begins. | `workflow`, `validation`, `utils` |
| `manifest.py` | Module | Generates workflow manifests consumed by tooling/docs. | `tooling.docs`, `workflow` |
| `output.py` | Module | `ActionOutputManager`: loads upstream outputs and resolves version correlation. Defines the public `AllVersionsFilteredError`; `resolve_correlated_input` delegates to the correlator and propagates its raise. `detect_explicit_version_consumption()` result is lazy-cached per instance. | `output`, `workflow` |
| `skip.py` | Module | Skip logic used when upstream items fail or guard conditions filter them. | `validation`, `workflow` |
| `state.py` | Module | `ActionStatus(str, Enum)` — typed action lifecycle statuses (`PENDING`, `RUNNING`, `BATCH_SUBMITTED`, `CHECKING_BATCH`, `COMPLETED`, `COMPLETED_WITH_FAILURES`, `FAILED`, `SKIPPED`, `INTERRUPTED`). `COMPLETED_STATUSES`, `TERMINAL_STATUSES`, `RETRYABLE_STATUSES` and `MID_PROCESSING_STATUSES` frozensets derived from enum. `ActionStateManager` — manages action execution state persistence and queries. Key methods: `is_failed()`, `is_skipped()`, `is_terminal()`, `is_in_progress()`, `get_pending_actions()`, `get_skipped_actions()`, `is_workflow_done()`, `get_summary()`, `mark_running_as_failed()`, `mark_running_as_interrupted()`. When the run-level sweep (`mark_running_as_failed`, `mark_running_as_interrupted`) takes an action out of `CHECKING_BATCH`, it marks it (`stopped_collecting`) in the same write, so the reset can keep the records of the files it had collected. Any later status change, by `update_status` or a bulk transition, drops the mark. `reopen(names)` puts several actions back to pending in one write, which is how a reset takes an action and everything that reads it together; it also removes the retired `max_records` marker, which `adopt_truncation_marker` leaves in place when it reports a truncation so that nothing between the read and the reopening write can lose it. | `workflow`, `state_management` |

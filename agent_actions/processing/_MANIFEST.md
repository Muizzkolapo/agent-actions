# Processing Manifest

## Overview

Shared processing utilities used by batch/online runners: enrichment, error handling,
lineage helpers, recovery flows, and transformation pipelines.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [invocation](invocation/) | LLM invocation strategies (online/batch) for unified execution. |
| [recovery](recovery/_MANIFEST.md) | Retry, checkpoint, and recovery helpers for failed batches. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_context_adapter.py` | Module | Adapts batch state to `ProcessingContext` + `ProcessingResult` for the shared `EnrichmentPipeline`. | `batch`, `enrichment` |
| `enrichment.py` | Module | Adds metadata (timestamps, run IDs) to processed items. | `logging`, `workflow` |
| `error_handling.py` | Module | `ProcessorErrorHandlerMixin` for wrapping file loading/processing logic. | `logging` |
| `exhausted_builder.py` | Module | Builds reports once a workflow’s retries are exhausted. | `validation`, `logging` |
| `helpers.py` | Module | Shared helpers (UUID construction, tuple flattening) for processors. | `processing` |
| `processor.py` | Module | Base processor that glues loaders, transformers, and error handling. | `input`, `processing` |
| `result_collector.py` | Module | Collects main vs side outputs, handles duplicates. Counts UNPROCESSED results separately from successes. | `output` |
| `prepared_task.py` | Module | `GuardStatus` enum (PASSED, SKIPPED, FILTERED, UPSTREAM_UNPROCESSED), `PreparedTask` dataclass, and `PreparationContext` (carries `mode: RunMode` directly). | `typing` |
| `task_preparer.py` | Module | Unified task preparation (normalize, prompt, guard) for batch/online. Short-circuits upstream-unprocessed records before context loading. | `input`, `prompt` |
| `types.py` | Module | `ProcessingStatus` enum (SUCCESS, SKIPPED, FILTERED, FAILED, EXHAUSTED, DEFERRED, UNPROCESSED), `ProcessingResult` factories, and `ProcessingContext` (uses `RunMode` for mode). | `typing` |

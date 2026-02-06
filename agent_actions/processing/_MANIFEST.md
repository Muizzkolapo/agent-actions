# Processing Manifest

## Overview

Shared processing utilities used by batch/realtime runners: enrichment, error handling,
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
| `result_collector.py` | Module | Collects main vs side outputs, handles duplicates. | `output` |
| `task_preparer.py` | Module | Unified task preparation (normalize, prompt, guard) for batch/online. | `input`, `prompt` |
| `types.py` | Module | Shared typed dicts/enums used across processors. | `typing` |

# Events Manifest

## Overview

Event-driven logging helpers that surface telemetry events (run results, cache hits)
and provide formatter hooks for the CLI/tracing system.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [handlers](handlers/_MANIFEST.md) | Console/event handlers used by logging. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `formatters.py` | Module | Formatters that render runtime events for CLI output. | `logging`, `cli` |
| `types.py` | Module | Defines `EventCategories` and `_safe_value_repr`. No re-exports — consumers import from category modules directly. | `logging` |
| `workflow_events.py` | Module | Workflow lifecycle (W) and action execution (A) events. 8 classes. | `logging` |
| `batch_events.py` | Module | Batch processing events (B prefix). 12 classes. | `logging` |
| `llm_events.py` | Module | LLM interaction (L) and template rendering (T) events. 9 classes. | `logging` |
| `validation_events.py` | Module | Validation (V), data parsing (D), guard (G), and recovery (R) events. 12 classes. | `logging` |
| `cache_events.py` | Module | Cache lifecycle events (C prefix). 6 classes. | `logging` |
| `initialization_events.py` | Module | Configuration (F), environment (E), initialization (I), and plugin (P) events. 24 classes. | `logging` |
| `io_events.py` | Module | File I/O (FIO), schema operations (SO), and context introspection (CX) events. 13 classes. | `logging` |
| `data_pipeline_events.py` | Module | Data validation (DV), transformation (DT), record processing (RP), batch processing (BP), and result collection (RC) events. 20 classes. | `logging` |

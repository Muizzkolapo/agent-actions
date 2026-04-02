# Workflow Managers Manifest

## Overview

Tracks workflow artifacts, batching, loops, state, and skip logic used by the runner.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `artifacts.py` | Module | Helpers that manage artefact directories/files during runs. | `file_io`, `workflow` |
| `batch.py` | Module | Batch helpers that coordinate chunked execution. | `llm.batch`, `processing` |
| `loop.py` | Module | VersionOutputCorrelator — version output correlation for parallel map-reduce patterns. | `workflow`, `validation` |
| `manifest.py` | Module | Generates workflow manifests consumed by tooling/docs. | `tooling.docs`, `workflow` |
| `output.py` | Module | `ActionOutputManager`: loads upstream outputs, resolves version correlation, creates passthrough outputs. `detect_explicit_version_consumption()` result is lazy-cached per instance to avoid redundant computation. | `output`, `workflow` |
| `skip.py` | Module | Skip logic used when upstream items fail or guard conditions filter them. | `validation`, `workflow` |
| `state.py` | Module | ActionStateManager — manages action execution state persistence and queries. Terminal states: `completed`, `failed`, `skipped`. Key methods: `is_failed()`, `is_skipped()`, `get_pending_actions()`, `is_workflow_done()`, `get_summary()`. | `workflow`, `state_management` |

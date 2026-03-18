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
| `output.py` | Module | Output-specific state tracking and side-output handling. | `output`, `workflow` |
| `skip.py` | Module | Skip logic used when upstream items fail or guard conditions filter them. | `validation`, `workflow` |
| `state.py` | Module | ActionStateManager — manages action execution state persistence and queries. | `workflow`, `state_management` |

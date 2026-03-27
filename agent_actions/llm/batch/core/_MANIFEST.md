# Batch Core Manifest

## Overview

Core batch helpers describe workflow batch metadata, constants, and embodied models
shared by the CLI, service layer, and infrastructure components.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_constants.py` | Module | Batch-specific constants (default chunk sizes, status codes). | `llm.batch` |
| `batch_context_metadata.py` | Module | Metadata helpers for preserving context (session IDs, run IDs). | `logging`, `workflow` |
| `batch_models.py` | Module | Typed models (dataclasses) that represent batch run state and inputs. `BatchJobEntry.from_dict()` filters unknown keys via `dataclasses.fields()` to tolerate schema evolution. | `typing`, `validation` |

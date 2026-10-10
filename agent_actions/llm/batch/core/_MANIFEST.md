# Batch Core Manifest

## Overview

Core batch helpers describe workflow batch metadata, constants, and embodied models
shared by the CLI, service layer, and infrastructure components.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_constants.py` | Module | Batch enums (`BatchStatus`, `FilterStatus`, `RecoveryType`, `RecoveryPhase`, `OnExhaustedPolicy`) and `ContextMetaKeys`, the context-map keys a tool is never handed (`all_internal_keys`), among them the error that failed a record's preparation (`PREP_ERROR`). `coerce_recovery_phase`/`coerce_recovery_type` are the only string-to-enum entry points for the two recovery enums: both refuse a name from a retired mechanism with `RetiredRecoveryState` rather than coercing it or letting a bare `ValueError` reach a caller that would skip the entry. | `llm.batch` |
| `batch_context_metadata.py` | Module | Metadata helpers for preserving context (session IDs, run IDs). | `logging`, `workflow` |
| `batch_models.py` | Module | Typed models (dataclasses) that represent batch run state and inputs. `BatchJobEntry.from_dict()` filters unknown keys via `dataclasses.fields()` to tolerate schema evolution. `BatchJobEntry.is_settled` is an entry the provider failed or cancelled that a collect pass has stamped `collected_at` once it marked its records failed, and `BatchRegistryStats.overall_status` rolls `settled` entries up with completed ones, so one holds an action no more than a collected batch does. `SubmissionResult.passthrough` says why no batch was sent: `{"type": "written"}` when submission wrote the file itself, `{"carry_forward_only": True}` when no record was left to send, every one already done or none there; submission then writes the file for this run's inputs if it holds a row of a record that left. | `typing`, `validation` |

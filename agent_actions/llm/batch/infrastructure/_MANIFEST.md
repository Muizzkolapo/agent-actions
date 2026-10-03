# Batch Infrastructure Manifest

## Overview

Infrastructure modules resolve context, job management, and file handling for
batch services that orchestrate runs outside online mode.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client_resolver.py` | Module | Returns the appropriate provider/batch client per agent config. | `llm.providers`, `validation` |
| `batch_data_loader.py` | Module | Loads and prepares batched input payloads for processors. | `input`, `preprocessing` |
| `context.py` | Module | Batch context builders and metadata propagation helpers. Persists three things per (action, batch) under storage metadata. The context map (`batch_context:…`) holds the rows that were submitted. The run's inputs (`batch_inputs:…`) hold the input above every narrowing — the record limit, a repair's named records, and the disposition gate all sit between the two — as an object mapping each identity to the staged record it descends from; a batch submitted earlier recorded a bare list, which still reads. The upstream pool (`batch_pool:…`), written by the runner through `save_upstream_pool`, holds every upstream record that exists for the file above the guard drop, or null where that is not known. Carry-forward reads the last two, because a record dropped by any narrowing still holds stored rows it must carry. `load_batch_inputs` reports an unrecorded input (`None`) apart from one recorded as empty, and warns on a recording it cannot read; `load_batch_input_ancestors` and `load_upstream_pool` return `None` for anything that is not an identity-to-identity object, without a second warning. None of them raises, since the reader's fallback is to carry every row and raising would abandon a batch the provider has already answered. All three are cleared by `clear_batch_state`. | `logging`, `workflow`, `storage` |
| `job_manager.py` | Module | Job lifecycle controller that tracks active batch runs. | `logging`, `tooling.docs` |
| `recovery_state.py` | Module | `RecoveryState`: cross-pass retry/repair state persisted to storage metadata between runs, so a deferred batch resumes where it stopped. Its `phase` goes through `coerce_recovery_phase`, so a row naming a phase this version does not run refuses rather than resuming into a handler that cannot act on it. | `storage`, `llm.batch.core` |
| `registry.py` | Module | `BatchRegistryManager`: thread-safe CRUD over the batch job registry, persisted as storage-backend metadata keyed by action. `are_all_jobs_completed()` releases the lock before network I/O to prevent thread starvation. A malformed entry is skipped with a warning but written back on every save, because the stored blob is the only thing naming its batch and a reclaim has to be able to read the id; a save or a remove on that key retires it. `batch_ids()` reads those ids as stored, bypassing the model for the same reason. One naming a retired recovery type is not skipped at all, because dropping it makes its parent look unsubmitted. | `llm.providers`, `logging`, `storage` |

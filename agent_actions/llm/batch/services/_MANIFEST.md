# Batch Services Manifest

## Overview

Services that coordinate batch submission, retrieval, and processing updates.

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `BatchSubmissionService._submit_to_provider()` | `.agac/batch_state/{batch_id}.json` | Deletes | — |
| `register_recovery_batch()` | `.agac/batch_state/{batch_id}.json` | Deletes | — |
| `process_recovery_batch()` | `.agac/batch_state/{batch_id}.json` | Deletes | — |
| `cleanup_recovery()` | `.agac/batch_state/{batch_id}.json` | Deletes | — |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `processing.py` | Module | Service that orchestrates batch processing pipelines (load, transform, execute). Delegates retry to `retry.py` and recovery/finalization to `processing_recovery.py`. | `processing`, `logging` |
| `processing_recovery.py` | Module | Recovery and finalization functions extracted from `BatchProcessingService`: recovery batch handling, retry and repair recovery, repair submission, output finalization. `finalize_batch_output` reads the run's recorded input (`batch_inputs:{action}:{file}`) and hands it to the write, which is what lets carry-forward tell a producer that is gone from one this run did not answer for; a recovery round reads its parent's recording, since it finalizes under `parent_file_name`. | `processing`, `retry`, `logging` |
| `retrieval.py` | Module | Pulls completed batch results and cleans up state. | `output`, `workflow` |
| `retry.py` | Module | Facade for `BatchRetryService`. Delegates to `retry_ops` and `shared.retrieve_and_reconcile`. | `retry_ops`, `shared` |
| `repair_ops.py` | Module | `repair_expectations`, `submit_repair_batch`, `pool_records`, `stamp_exhausted`, `apply_exhaustion_policy` | Drives the `expect:` repair loop in batch: splits graduated from still-failing, sends the failures back with their feedback, and applies `on_exhausted` once the rounds are spent. `pool_records` is the accumulator the loop and the recovery state machine share, keyed by record id so a resume cannot ship a record twice. |
| `retry_ops.py` | Module | Retry-specific operations: submit retry batches, resubmit missing records, process retry results, build exhausted recovery metadata. | `retry_polling`, `llm.providers`, `processing` |
| `retry_serialization.py` | Module | Serialize/deserialize `BatchResult` objects for JSON persistence. | `llm.providers`, `processing.types` |
| `retry_polling.py` | Module | Batch polling (`wait_for_batch_completion`) and validation module import (`import_validation_module`). | `llm.providers`, `logging.events` |
| `shared.py` | Module | Shared utilities (retrieve_and_reconcile) used by both processing and retrieval services. | `llm.providers`, `processing` |
| `submission.py` | Module | Submits batch jobs to the scheduler or provider. Records the run's input above every narrowing (`batch_inputs:{action}:{file}`, beside the context map) for carry-forward to read back at finalization — taken from the caller's pre-narrowing list, never from the `data` it submits, which the record limit, a repair and the disposition gate have all narrowed. A repair arriving without that list is refused rather than narrowed, as `UnifiedProcessor.process` refuses it online. | `llm.providers`, `logging` |

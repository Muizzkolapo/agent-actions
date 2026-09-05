# Batch Services Manifest

## Overview

Services that coordinate batch submission, retrieval, and processing updates.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `processing.py` | Module | Service that orchestrates batch processing pipelines (load, transform, execute). Delegates retry/reprompt to `retry.py` and recovery/finalization to `processing_recovery.py`. | `processing`, `logging` |
| `processing_recovery.py` | Module | Recovery and finalization functions extracted from `BatchProcessingService`: recovery batch handling, retry/reprompt recovery, reprompt submission, output finalization. Record dispositions delegated to `processing.result_collector.write_record_dispositions`. | `processing`, `retry`, `logging` |
| `retrieval.py` | Module | Pulls completed batch results and cleans up state. | `output`, `workflow` |
| `retry.py` | Module | Facade for `BatchRetryService`. Delegates to `retry_ops`, `reprompt_ops`, `retry_serialization`, and `retry_polling`. Re-exports module-level names for backward compatibility. | `retry_ops`, `reprompt_ops`, `retry_serialization`, `retry_polling` |
| `repair_ops.py` | Module | `repair_expectations`, `submit_repair_batch`, `pool_records`, `stamp_exhausted`, `apply_exhaustion_policy` | Drives the `expect:` repair loop in batch: splits graduated from still-failing, sends the failures back with their feedback, and applies `on_exhausted` once the rounds are spent. `pool_records` is the shared accumulator both this loop and reprompt use, keyed by record id so a resume cannot ship a record twice. |
| `resubmission.py` | Module | `resubmit_round`, `RoundOutcome` | One resubmission round — prepare, submit, wait, retrieve, reconcile — shared by reprompt and repair so the two cannot drift on what resubmitting a set means. `attempt` is a required keyword: a call site that loses it would stamp every round's prompt trace as round 0. |
| `retry_ops.py` | Module | Retry-specific operations: submit retry batches, resubmit missing records, process retry results, build exhausted recovery metadata. | `retry_polling`, `llm.providers`, `processing` |
| `reprompt_ops.py` | Module | Reprompt/validation operations: validate results via UDF, submit reprompt batches, merge reprompt results, apply exhaustion metadata. | `retry_polling`, `llm.providers`, `processing` |
| `retry_serialization.py` | Module | Serialize/deserialize `BatchResult` objects for JSON persistence. | `llm.providers`, `processing.types` |
| `retry_polling.py` | Module | Batch polling (`wait_for_batch_completion`) and validation module import (`import_validation_module`). | `llm.providers`, `logging.events` |
| `shared.py` | Module | Shared utilities (retrieve_and_reconcile) used by both processing and retrieval services. | `llm.providers`, `processing` |
| `submission.py` | Module | Submits batch jobs to the scheduler or provider. | `llm.providers`, `logging` |

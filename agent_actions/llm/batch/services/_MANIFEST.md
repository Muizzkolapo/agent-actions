# Batch Services Manifest

## Overview

Services that coordinate batch submission, retrieval, and processing updates.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `processing.py` | Module | Service that orchestrates batch processing pipelines (load, transform, execute). Delegates retry/reprompt to `retry.py` and recovery/finalization to `processing_recovery.py`. | `processing`, `logging` |
| `processing_recovery.py` | Module | Recovery and finalization functions extracted from `BatchProcessingService`: recovery batch handling, retry/reprompt recovery, reprompt submission, output finalization, record dispositions. | `processing`, `retry`, `logging` |
| `retrieval.py` | Module | Pulls completed batch results and cleans up state. | `output`, `workflow` |
| `retry.py` | Module | Retry and reprompt logic for missing/failed batch records. Modern async methods + delegator stubs for legacy blocking methods. | `processing`, `llm.providers` |
| `retry_legacy.py` | Module | Deprecated blocking methods extracted from `retry.py` (retrieve_results_with_retry, validate_and_reprompt, wait_for_batch_completion). Only used by tests. | `retry`, `llm.providers` |
| `shared.py` | Module | Shared utilities (retrieve_and_reconcile) used by both processing and retrieval services. | `llm.providers`, `processing` |
| `submission.py` | Module | Submits batch jobs to the scheduler or provider. | `llm.providers`, `logging` |

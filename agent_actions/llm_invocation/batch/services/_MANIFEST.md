# Services Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_processing_service.py` | Module | Batch processing service for processing batch job results. | `errors`, `file_io`, `llm_invocation`, `utilities` |
| `BatchProcessingService` | Class | Service for processing batch job results. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_batch_results` | Method | Process batch results and integrate them into workflow output system. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_all_batch_results` | Method | Process all completed batch jobs in the registry. | - |
| `batch_retrieval_service.py` | Module | Batch retrieval service for downloading batch job results. | `errors`, `llm_invocation`, `utilities` |
| `BatchRetrievalService` | Class | Service for retrieving batch job results. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `retrieve_results` | Method | Retrieve and save results from a completed batch job. | - |
| `batch_retry_service.py` | Module | Batch retry service for handling batch job retries. | `errors`, `llm_invocation` |
| `BatchRetryService` | Class | Service for handling batch job retry operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `retry_batch_job` | Method | Manually retry a batch job. | - |
| `batch_submission_service.py` | Module | Batch submission service for submitting batch jobs. | `errors`, `llm_invocation`, `logging` |
| `BatchSubmissionService` | Class | Service for submitting batch jobs. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_batch_tasks` | Method | Prepare batch tasks from data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_status` | Method | Check the status of a batch job. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `submit_batch_job` | Method | Submit a batch job for processing. | - |

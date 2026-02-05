# Batch Services Manifest

## Overview

Services that coordinate batch submission, retrieval, and processing updates.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `processing.py` | Module | Service that orchestrates batch processing pipelines (load, transform, execute). Delegates retry/reprompt to `retry.py`. | `processing`, `logging` |
| `retrieval.py` | Module | Pulls completed batch results and cleans up state. | `output`, `workflow` |
| `retry.py` | Module | Retry and reprompt logic for missing/failed batch records. Extracted from `processing.py`. | `processing`, `llm.providers` |
| `shared.py` | Module | Shared utilities (retrieve_and_reconcile) used by both processing and retrieval services. | `llm.providers`, `processing` |
| `submission.py` | Module | Submits batch jobs to the scheduler or provider. | `llm.providers`, `logging` |

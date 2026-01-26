# Batch Services Manifest

## Overview

Services that coordinate batch submission, retrieval, and processing updates.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `processing.py` | Module | Service that orchestrates batch processing pipelines (load, transform, execute). | `processing`, `logging` |
| `retrieval.py` | Module | Pulls completed batch results and cleans up state. | `output`, `workflow` |
| `submission.py` | Module | Submits batch jobs to the scheduler or provider. | `llm.providers`, `logging` |

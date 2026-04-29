# Batch Processing Manifest

## Overview

Models that prepare batch inputs, reconcile outputs, and process results
before persisted results are written.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_passthrough_builder.py` | Module | Constructs passthrough records for batch guard filtering. | `preprocessing`, `lineage` |
| `preparator.py` | Module | Prepares batch workloads (chunking, formatting, batching). | `preprocessing`, `input` |
| `reconciler.py` | Module | Reconciles batch outputs with context; uses string-normalized custom_id for JSON compatibility. | `formatting`, `output` |
| `batch_result_strategy.py` | Module | Batch result processing strategy; converts raw BatchResult objects into enriched ProcessingResult records. | `processing`, `output` |

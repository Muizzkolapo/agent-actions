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
| `result_processor.py` | Module | Processes batch results into workflow format; normalizes custom_id to string for context lookups. | `processing`, `output` |

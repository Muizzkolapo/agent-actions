# Metadata Manifest

## Overview
Unified metadata system for consistent metadata extraction and tracking across batch and online processing modes.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `metadata_types.py` | Module | Dataclasses for metadata structures. | - |
| `ResponseMetadata` | Class | LLM response metadata (model, finish_reason, usage, etc.). | - |
| `RetryMetadata` | Class | Retry tracking metadata (was_retried, retry_attempts, etc.). | - |
| `UnifiedMetadata` | Class | Combined container for response and retry metadata. | - |
| `metadata_extractor.py` | Module | Metadata extraction service. | - |
| `MetadataExtractor` | Class | Provider-agnostic metadata extraction from LLM responses. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_from_response` | Method | Extract ResponseMetadata from any LLM response format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_retry_metadata` | Method | Build RetryMetadata with consistent structure. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_unified_metadata` | Method | Build UnifiedMetadata container. | - |
| `MetadataTimer` | Class | Context manager for tracking operation latency. | - |

# Metadata Manifest

## Overview

Unified metadata extraction for batch and online modes; normalizes provider
fields (model, status, usage) and exposes dataclasses for serialization.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `extractor.py` | Module | `MetadataExtractor` that inspects dict/object responses to pull provider, model, usage, latency, and request IDs. | `logging`, `errors` |
| `MetadataExtractor` | Class | Static methods `extract_from_response`, `_extract_from_dict`, `_extract_from_object`, and helpers (_extract_usage, _extract_raw_metadata) that handle OpenAI/Anthropic/object responses. | `logging` |
| `types.py` | Module | `ResponseMetadata` and `UnifiedMetadata` dataclasses with `to_dict`/`from_dict` helpers for consistent output metadata structures. | `logging`, `output` |

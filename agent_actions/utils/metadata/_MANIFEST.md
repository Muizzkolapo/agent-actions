# Metadata Manifest

## Overview

Unified metadata extraction for batch and online modes; normalizes provider
fields (model, status, usage) and exposes dataclasses for serialization.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `extractor.py` | Module | `MetadataExtractor.from_config` gives the provider (normalized through `PROVIDER_ALIASES`) and model an action's config names; it reads nothing of the answer. `MetadataTimer` times an operation. | `logging`, `errors` |
| `MetadataExtractor` | Class | `from_config(agent_config)`: the provider and model of an action's config, as `ResponseMetadata`. | `logging` |
| `types.py` | Module | `ResponseMetadata` and `UnifiedMetadata` dataclasses with `to_dict`/`from_dict` helpers for consistent output metadata structures. | `logging`, `output` |

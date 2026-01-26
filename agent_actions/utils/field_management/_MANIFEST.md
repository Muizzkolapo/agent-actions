# Field Management Manifest

## Overview

Ensures all processed items expose `target_id`, `node_id`, `source_guid`, and
optional metadata no matter where they are constructed.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `manager.py` | Module | `FieldManager` utility that adds/validates required fields, creates standard processed items, and appends metadata. | `id_generation`, `lineage` |
| `FieldManager` | Class | Provides `ensure_required_fields`, `create_processed_item`, and `add_metadata` helpers used across passthrough/batch builders. | `id_generation`, `lineage` |

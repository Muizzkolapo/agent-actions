# Correlation Manifest

## Overview

Deterministic version correlation IDs that tie each source_guid to a consistent
version iteration across workflow sessions.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `version_id.py` | Module | `VersionIdGenerator` that caches correlation IDs per workflow/session, supports GUID-based and position-based IDs, and exposes helpers for adding IDs to items. | `lineage`, `logging` |
| `VersionIdGenerator` | Class | Thread-safe registry with helper methods like `get_or_create_version_correlation_id`, `_generate_deterministic_correlation_id`, `clear()` (short alias for `clear_version_correlation_registry()`), and payload helpers for object augmentation. | `lineage`, `logging` |

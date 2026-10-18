# Preflight Manifest

## Overview

Pre-flight validators ensure vendor compatibility, path safety, and CLI arguments
before workflows execute.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `error_formatter.py` | Module | Formats validation failures into user-readable messages. | `logging`, `validation` |
| `guard_validation.py` | Module | `validate_guard_conditions`: parses each expanded guard `clause` and refuses a parse failure, a bare identifier on a comparison's right, an unknown function or wrong arity, a read through `action`, `prompt` or `schema` (no record carries them, so every record would be filtered; 1512), and an unnamespaced field that cannot resolve. Wired at `PreflightService.validate`. | `validation` |
| `path_validator.py` | Module | Ensures file paths referenced in configs are safe and exist. | `file_io`, `validation` |
| `vendor_compatibility_validator.py` | Module | Ensures vendor configs meet limit/feature requirements. `VALID_VENDORS` is derived from `llm.realtime.services.invocation.CLIENT_REGISTRY` (single source of truth). Vendor capabilities are read from each client class's `CAPABILITIES` class variable at runtime via `_resolve_capabilities()` — no separate dict to maintain. | `llm.realtime`, `validation` |
| `VendorCompatibilityValidator` | Class | Validates vendor compatibility for a given workflow config. Caches capability lookups across calls. | `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_cache` | Classmethod | Clears the vendor capability cache; call in test fixtures to prevent cross-test contamination. | - |

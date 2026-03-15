# Preflight Manifest

## Overview

Pre-flight validators ensure vendor compatibility, path safety, and CLI arguments
before workflows execute.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `error_formatter.py` | Module | Formats validation failures into user-readable messages. | `logging`, `validation` |
| `path_validator.py` | Module | Ensures file paths referenced in configs are safe and exist. | `file_io`, `validation` |
| `vendor_compatibility_validator.py` | Module | Ensures vendor configs meet limit/feature requirements. `VALID_VENDORS` is derived from `llm.realtime.services.invocation.CLIENT_REGISTRY` (single source of truth). Vendor capabilities are read from each client class's `CAPABILITIES` class variable at runtime via `_resolve_capabilities()` — no separate dict to maintain. | `llm.realtime.services.invocation`, `validation` |

# Preflight Manifest

## Overview

Pre-flight validators ensure vendor compatibility, path safety, and CLI arguments
before workflows execute.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `error_formatter.py` | Module | Formats validation failures into user-readable messages. | `logging`, `validation` |
| `guard_validation.py` | Module | `validate_guard_conditions`: parses each expanded guard `clause` and refuses a parse failure, a bare identifier on a comparison's right, an unknown function or wrong arity, a read through `action`, `prompt` or `schema` (no record carries them, so every record would be filtered; 1512), and an unnamespaced field that cannot resolve, a first action's included: its record holds the staged row under `source`, so a bare staged column is refused naming `source.<column>` (1535). An action counts as a first action only when it names no upstream by dependency or `context_scope` reference (`_named_upstreams`, the set the editor diagnostic builds); one naming an upstream only in its `context_scope` is offered that upstream's spelling, and its reach is refused by `find_reads_not_upstream`. The action's own name is never offered under `source`. Each such name is reported once per clause. Wired at `PreflightService.validate`. | `validation` |
| `resolution_service.py` | Module | `WorkflowResolutionService`: API keys, seed files and vendor run-mode checks. Every `seed.<key>` a prompt, guard or `context_scope` reads must be declared in its action's `context_scope.seed`; this holds when the workflow has no seed directory too, so a guard reading `seed.*` with nothing declared is refused rather than filtering every record (1525). A seed file is parsed with `StaticDataLoader.parse_file`, the loader the run uses, so a YAML, CSV or text seed passes as it runs and a malformed one is refused with its format's parse error (1533). | `validation`, `prompt.context` |
| `path_validator.py` | Module | Ensures file paths referenced in configs are safe and exist. | `file_io`, `validation` |
| `vendor_compatibility_validator.py` | Module | Ensures vendor configs meet limit/feature requirements. `VALID_VENDORS` is derived from `llm.realtime.services.invocation.CLIENT_REGISTRY` (single source of truth). Vendor capabilities are read from each client class's `CAPABILITIES` class variable at runtime via `_resolve_capabilities()` — no separate dict to maintain. | `llm.realtime`, `validation` |
| `VendorCompatibilityValidator` | Class | Validates vendor compatibility for a given workflow config. Caches capability lookups across calls. | `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_cache` | Classmethod | Clears the vendor capability cache; call in test fixtures to prevent cross-test contamination. | - |

# Prompt Context Manifest

## Overview

Context helpers build the field-context used by prompts and guards, with static
loaders for cataloging prompts at documentation time.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package init — added in Wave 11 (G-6) to prevent `ModuleNotFoundError` on some import paths. | — |
| `builder.py` | Module | `ContextBuilder` helpers that resolve field references into prompt context data. | `preprocessing`, `validation` |
| ~~`scope.py`~~ | Deleted | Facade removed. Consumers import directly from the 6 `scope_*` modules. | — |
| `scope_parsing.py` | Module | Field reference parsing and action name extraction utilities. | `preprocessing` |
| `scope_inference.py` | Module | Dependency inference: fan-in detection, version branch expansion, input/context source resolution. | `preprocessing` |
| `scope_application.py` | Module | Context scope application: observe/passthrough/drop filtering, LLM context formatting. | `preprocessing` |
| `scope_namespace.py` | Module | Namespace enrichment, historical data loading, field filtering, and allowed-fields extraction. | `preprocessing` |
| `scope_builder.py` | Module | `build_field_context_with_history`: assembles source/dependency/version/workflow namespaces. | `preprocessing` |
| `scope_file_mode.py` | Module | File-mode observe filtering with cross-namespace resolution, version namespace detection, and ancestry-aware caching. | `preprocessing` |
| `static_loader.py` | Module | Static prompt loader used during docs generation to read prompt store files. | `tooling.docs`, `file_io` |

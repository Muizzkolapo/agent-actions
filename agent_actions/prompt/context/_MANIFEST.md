# Prompt Context Manifest

## Overview

Context helpers build the field-context used by prompts and guards, with static
loaders for cataloging prompts at documentation time.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package init. Consumers import directly from submodules. | — |
| `builder.py` | Module | `ContextBuilder` helpers that resolve field references into prompt context data. | `preprocessing`, `validation` |
| ~~`scope.py`~~ | Deleted | Facade removed. Consumers import directly from the 6 `scope_*` modules. | — |
| `scope_parsing.py` | Module | Field reference parsing and action name extraction utilities. `parse_field_reference()` delegates to `ReferenceParser` from `field_resolution` package. | `preprocessing` |
| `scope_inference.py` | Module | Dependency inference: fan-in detection, version branch expansion, input/context source resolution. | `preprocessing` |
| `null_namespace.py` | Module | `NullNamespace` sentinel and `is_null_namespace()` helper for skipped/filtered upstream namespaces. Used by `scope_application`, `scope_builder`, and guard evaluator `ast_nodes`. | `preprocessing` |
| `scope_application.py` | Module | Context scope application: observe/passthrough/drop filtering for RECORD mode (`apply_context_scope`) and FILE mode (`apply_context_scope_for_records`), LLM context formatting. | `preprocessing` |
| `scope_namespace.py` | Module | Namespace enrichment, field filtering, and allowed-fields extraction. | `preprocessing` |
| `scope_builder.py` | Module | `build_field_context_with_history`: assembles source/dependency/version/workflow namespaces via composable builder classes (`SourceNamespaceBuilder`, `DependencyNamespaceBuilder`, `VersionNamespaceBuilder`, `WorkflowMetadataBuilder`). Convergence point for source data validation (see design note). | `preprocessing`, `staging.field_validation` |
| ~~`scope_file_mode.py`~~ | Deleted | FILE-mode observe merged into `scope_application.py:apply_context_scope_for_records`. | — |
| `static_loader.py` | Module | Static prompt loader used during docs generation to read prompt store files. | `tooling.docs`, `file_io` |

## Design Notes

### Source data: four retrieval paths, one convergence point

Source data (the user's original staging input) reaches `SourceNamespaceBuilder.build()` in
`scope_builder.py` through four paths, each serving a different pipeline lifecycle stage:

| Path | When | How source data arrives | Entry point |
|------|------|------------------------|-------------|
| **Staging file load** | First action, initial run | Read from the user-configured `data_source` path (`folder` + `file_type` in workflow config) by `FileReader` | `initial_pipeline.process_initial_stage()` |
| **Storage lookup** | Downstream actions | Saved to storage during first action; retrieved by `source_guid` | `task_preparer._get_source_content()` |
| **FILE mode index** | FILE-granularity actions | Resolved per-`source_guid` from a shared source index; a miss against a multi-record pool skips the record with reason `source_unresolved` (single-record pools resolve unambiguously) | `scope_application._resolve_source_content()` |
| **Batch resume** | Batch re-run after prior submission | Records already in memory/storage from prior batch prep | `params.data` pre-loaded, skips `initial_pipeline` |

The data is the same in all four cases — the user's original staging fields. The paths
differ because of *where the data lives* at each stage (disk → storage → index → memory).

`SourceNamespaceBuilder.build()` is the single convergence point where all four paths write to
`field_context["source"]`. Validation for reserved namespace collisions runs here to
cover all paths regardless of how the data entered the pipeline.

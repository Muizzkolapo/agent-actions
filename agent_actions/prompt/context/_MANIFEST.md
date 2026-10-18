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
| `scope_inference.py` | Module | Dependency inference: every `dependencies` entry is an input source (a fan-in included, whatever the order), actions named only in `context_scope` or the prompt are context sources; version branch expansion (`expand_version_base_names`, also used by preflight to expand `dependencies`). | `preprocessing` |
| `null_namespace.py` | Module | `NullNamespace` sentinel for a declared dependency the record has no data for; its `reason` is what the record shows (`skipped` by a guard on that action per `_state_history`, `no_output` when a history below its cap records no such skip, `null` when no history can say, `absent`, `no_declared_fields`). `is_null_namespace()` helper; `diagnose()` gives the render error's first sentence, naming a guard only for `skipped`. Used by `scope_application`, `scope_builder`, `prompt/service.py` and guard evaluator `ast_nodes`. | `preprocessing` |
| `scope_application.py` | Module | Context scope application: observe/passthrough/drop filtering for RECORD mode (`apply_context_scope`) and FILE mode (`apply_context_scope_for_records`). The prompt-context gate keeps the framework namespaces and the names a version promotes to the top level (`i`, `idx`, a custom `param`). | `preprocessing` |
| `scope_namespace.py` | Module | Namespace enrichment, field filtering, and allowed-fields extraction. `_extract_content_data` subtracts `_RECORD_METADATA_KEYS` from a record with no `content` envelope; that guess is why a pool row is required to carry one before it reaches here. The branch remains for the record being processed, whose namespaces are the framework's either way. | `preprocessing` |
| `scope_builder.py` | Module | `build_field_context_with_history`: assembles source/dependency/version/workflow namespaces via composable builder classes (`SourceNamespaceBuilder`, `DependencyNamespaceBuilder`, `VersionNamespaceBuilder`, `WorkflowMetadataBuilder`). Convergence point for source data validation (see design note). | `preprocessing`, `staging.field_validation` |
| ~~`scope_file_mode.py`~~ | Deleted | FILE-mode observe merged into `scope_application.py:apply_context_scope_for_records`. | — |
| `seed_entry.py` | Module | One `context_scope.seed` entry: `parse_seed_entry` accepts a file path or a `{select_by: source.<field>, files: {value: path}}` mapping; `SeedEntry.file_for(record_fields)` picks the record's file and refuses a missing, unknown or non-scalar value (`SeedSelectionError`); `selected_seed_entries` lists every selected entry of a workflow. Shared by the loader, preflight, the staging check and `inspect context`. | `preprocessing`, `validation`, `cli` |
| `static_loader.py` | Module | `StaticDataLoader`: loads seed files (JSON, YAML, CSV, text) for one record with path traversal prevention and a cache keyed by path, size and mtime; a selected entry's file is chosen from the record's `source` fields. `shared_static_data_loader` gives one loader per seed directory for the process, so a file is parsed once; what it returns is shared and must not be written to (the guard context's seed). `StaticDataLoader.parse_file` parses one file by extension; pre-flight seed checks call it, so they read a file as the run does. CSV is read with `utf-8-sig` and `newline=""`, so a byte order mark is not part of the first key and a quoted `\r\n` is kept. | `prompt.service`, `processing`, `validation.preflight` |

## Design Notes

### Source data: four retrieval paths, one convergence point

Source data (the user's original staging input) reaches `SourceNamespaceBuilder.build()` in
`scope_builder.py` through four paths, each serving a different pipeline lifecycle stage:

| Path | When | How source data arrives | Entry point |
|------|------|------------------------|-------------|
| **Staging file load** | First action, initial run | Read from the user-configured `data_source` path (`folder` + `file_type` in workflow config) by `FileReader` | `initial_pipeline.process_initial_stage()` |
| **Storage lookup** | Downstream actions | Saved to storage during first action; retrieved by identity (own `source_guid`, then `parent_source_guid`), then the `source` namespace the record carries for a record the pool cannot place, then `None`. Same order as the FILE-mode path below, so a record that resolves at all resolves to the same enveloped pool row under either granularity, for the prompt and for observe/passthrough output. A guard condition is covered as well: the evaluator no longer promotes a carried framework namespace over the resolved one, and the FILE-mode prefilter evaluates the guard against the stored record rather than the `context_scope`-shaped copy, so both granularities read the resolved namespace. One further difference remains, recorded as a decision: when nothing resolves, FILE mode skips the record with a disposition and this path proceeds without a `source` namespace. The same shape covers an `observe` whose field is absent (#1140): the FILE pass runs before the guard, so the record is removed with its scope reason and no guard verdict is recorded, while this path reaches the guard first and fails at preparation, which `_build_prep_failed_result` classifies FAILED on purpose. Both refuse the record; they differ in the accounting. Unresolved deliberately — each candidate answer overturns a decision that is already deliberate elsewhere — and pinned on both granularities by `tests/unit/processing/test_the_scope_skip_divergence_is_pinned.py` so a change has to be argued for rather than drift. The two paths no longer differ on a flat pool row — FILE stripped the record-keeping keys and this path did not, so the same row read as two different documents; both now refuse a row with no `content` envelope rather than guess which of its keys are the document's | `processing.source_resolution.resolve_source_content()` |
| **FILE mode index** | FILE-granularity actions | Resolved by identity from a shared source index: own `source_guid`, then carried `parent_source_guid` (a minted row's producer, or an inherited ancestor); a miss on both falls back to the `source` namespace the record carries in its own content (as the RECORD-mode resolver also does last), and only then skips it with reason `source_unresolved` (never positionally). A skip names the input position it dropped, which is how a FILE-mode caller takes the same records out of the pre-observe list it holds beside this one. A matched row must carry a `content` namespace dict; a flat one raises `DataValidationError` rather than have `_RECORD_METADATA_KEYS` guess which of its keys are the document's, which discarded a user field named `metadata` or `lineage` | `scope_application._resolve_source_content()` |
| **Batch resume** | Batch re-run after prior submission | Records already in memory/storage from prior batch prep | `params.data` pre-loaded, skips `initial_pipeline` |

The data is the same in all four cases — the user's original staging fields. The paths
differ because of *where the data lives* at each stage (disk → storage → index → memory).

`SourceNamespaceBuilder.build()` is the single convergence point where all four paths write to
`field_context["source"]`. Validation for reserved namespace collisions runs here to
cover all paths regardless of how the data entered the pipeline.

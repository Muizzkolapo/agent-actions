# Input Manifest

**[> Architecture deep-dive (ARCHITECTURE.md)](ARCHITECTURE.md)**

## Overview

Input package centralizes context helpers, file loaders, and preprocessing pipelines
for the Agent Actions workflow (context scope normalization, guard evaluation,
and chunking/lineage support).

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [context](context/_MANIFEST.md) | Context normalization and context_scope expansion helpers. |
| [loaders](loaders/_MANIFEST.md) | File loaders for JSON/XML/text/tabular/UDF discovery and asynchronous base classes. |
| [preprocessing](preprocessing/_MANIFEST.md) | Chunking, filter parsing, field resolution, stage bootstrapping, and transformation helper packages. |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `FileReader.read()` | `agent_io/staging/` | Reads | — |
| `SourceDataLoader.load_source_data()` | `agent_io/target/{action}/` | Reads | — |
| `resolve_start_node_data_source()` | `agent_io/staging/` | Reads | `data_source` |
| `discover_udfs()` | `tools/{workflow}/*.py` | Reads | — |
| `validate_udf_references()` | `tools/{workflow}/*.py` | Validates | `impl`, `guard` (`udf:` conditions) |
| `normalize_context_scope()` | `agent_config/{workflow}.yml` | Transforms | `context_scope` |
| `normalize_all_agent_configs()` | `agent_config/{workflow}.yml` | Transforms | `context_scope` |
| `process_initial_stage()` | `agent_io/staging/` | Reads | `run_mode`, `record_limit`, `chunk_config`, `data_source` (`file_type`) |
| `validate_source_reads_below()` | `agent_io/staging/`, `agent_config/{workflow}.yml`, `prompt_store/{workflow}.md` | Validates | `context_scope.observe`, `context_scope.passthrough`, `prompt`, `guard`, `dependencies` |
| `GuardFilter.filter_item()` | `agent_config/{workflow}.yml` | Reads | `guard.where` |
| `GuardEvaluator.evaluate()` | `agent_config/{workflow}.yml` | Reads | `guard` |

**Internal only**: `ReferenceParser`, `FieldReferenceResolver`, `ReferenceValidator`, `SchemaFieldValidator`, `EvaluationContextProvider`, `Tokenizer` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `storage` | outbound | Uses StorageBackend for source/target reads via SourceDataLoader |
| `output` | outbound | Uses FileWriter and UnifiedSourceDataSaver for initial-stage writes |
| `config` | outbound | Reads workflow configuration, data_source settings, and schema paths |
| `processing` | outbound | Delegates record processing to UnifiedProcessor |
| `prompt` | outbound | Validates staged data against prompt templates |
| `workflow` | inbound | Workflow executor calls process_initial_stage and context normalization |
| `workflow` | outbound | The first stage builds its batch context with `ProcessingPipeline`, names a batch file by the top-level files the walk processes (`should_skip_item`), and counts the files the walk stages (`staged_input_fingerprint`) to decide whether a later action's `source` read is refused or warned of |
| `validation` | inbound | Uses guard evaluation and field resolution for preflight checks |
| `validation` | outbound | Staging extracts later actions' `source` reads with `ReferenceExtractor`, resolving `$` prompts as the seed check does (`WorkflowResolutionService._resolve_prompt_for_extraction`) |

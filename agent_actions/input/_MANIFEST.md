# Input Manifest

## Overview

Input package centralizes context helpers, file loaders, and preprocessing pipelines
for the Agent Actions workflow (context scope normalization, guard evaluation,
and chunking/lineage support).

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [context](context/_MANIFEST.md) | Context normalization, historical node retrieval, and context_scope expansion helpers. |
| [loaders](loaders/_MANIFEST.md) | File loaders for JSON/XML/text/tabular/UDF discovery and asynchronous base classes. |
| [preprocessing](preprocessing/_MANIFEST.md) | Chunking, filter parsing, field resolution, stage bootstrapping, and transformation helper packages. |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `FileReader.read()` | `agent_io/staging/` | Reads | — |
| `SourceDataLoader.load_source_data()` | `agent_io/target/{action}/` | Reads | — |
| `SourceDataLoader.save_source_data()` | `agent_io/target/{action}/` | Writes | — |
| `resolve_start_node_data_source()` | `agent_io/staging/` | Reads | `data_source` |
| `discover_udfs()` | `tools/{workflow}/*.py` | Reads | — |
| `validate_udf_references()` | `tools/{workflow}/*.py` | Validates | `impl` |
| `normalize_context_scope()` | `agent_config/{workflow}.yml` | Transforms | `context_scope` |
| `normalize_all_agent_configs()` | `agent_config/{workflow}.yml` | Transforms | `context_scope` |
| `HistoricalNodeDataLoader.load_historical_node_data()` | `agent_io/target/{action}/` | Reads | — |
| `process_initial_stage()` | `agent_io/staging/` | Reads | `run_mode`, `record_limit`, `chunk_config` |
| `GuardFilter.evaluate()` | `agent_config/{workflow}.yml` | Reads | `guard.where` |
| `GuardEvaluator.evaluate()` | `agent_config/{workflow}.yml` | Reads | `guard` |

**Internal only**: `ContextPreprocessor`, `FieldAnalyzer`, `FieldChunker`, `ReferenceParser`, `FieldReferenceResolver`, `ReferenceValidator`, `SchemaFieldValidator`, `EvaluationContextProvider`, `Tokenizer`, `DataProcessor` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `storage` | outbound | Uses StorageBackend for source/target reads via SourceDataLoader and HistoricalNodeDataLoader |
| `output` | outbound | Uses FileWriter and UnifiedSourceDataSaver for initial-stage writes |
| `config` | outbound | Reads workflow configuration, data_source settings, and schema paths |
| `processing` | outbound | Delegates record processing to RecordProcessor |
| `prompt` | outbound | Validates staged data against prompt templates |
| `workflow` | inbound | Workflow executor calls process_initial_stage and context normalization |
| `validation` | inbound | Uses guard evaluation and field resolution for preflight checks |

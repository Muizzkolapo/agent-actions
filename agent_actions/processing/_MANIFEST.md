# Processing Manifest

## Overview

Shared processing utilities used by batch/online runners: enrichment, error handling,
lineage helpers, recovery flows, and transformation pipelines.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [invocation](invocation/) | LLM invocation strategies (online/batch) for unified execution. |
| [strategies](strategies/) | Pipeline-level processing strategies for FILE-granularity modes (`FileToolStrategy`, `HITLStrategy`). |
| [recovery](recovery/_MANIFEST.md) | Retry, checkpoint, and recovery helpers for failed batches. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_context_adapter.py` | Module | Adapts batch state to `ProcessingContext` + `ProcessingResult` for the shared `EnrichmentPipeline`. | `batch`, `enrichment` |
| `enrichment.py` | Module | Adds metadata (timestamps, run IDs) to processed items. | `logging`, `workflow` |
| `error_handling.py` | Module | `ProcessorErrorHandlerMixin` for wrapping file loading/processing logic. | `logging` |
| `exhausted_builder.py` | Module | Builds reports once a workflow’s retries are exhausted. | `validation`, `logging` |
| `helpers.py` | Module | Shared helpers (UUID construction, tuple flattening) for processors. | `processing` |
| `record_helpers.py` | Module | Shared record assembly helpers: `build_tombstone`, `build_exhausted_tombstone`, `carry_framework_fields`, `apply_version_merge`, `extract_existing_content`. Used by all processing paths (online, batch, FILE). | `record`, `processing` |
| `result_collector.py` | Module | Collects main vs side outputs, handles duplicates. Counts UNPROCESSED results separately from successes. Exports `write_node_level_disposition` (node-level skip/passthrough) and `write_record_dispositions` (batch record dispositions). All `set_disposition` calls (except executor-level) are centralized here. | `output` |
| `prepared_task.py` | Module | `GuardStatus` enum (PASSED, SKIPPED, FILTERED, UPSTREAM_UNPROCESSED), `PreparedTask` dataclass, and `PreparationContext` (carries `mode: RunMode` directly). | `typing` |
| `task_preparer.py` | Module | Unified task preparation (normalize, prompt, guard) for batch/online. Short-circuits upstream-unprocessed records before context loading. | `input`, `prompt` |
| `types.py` | Module | `ProcessingStatus` enum (SUCCESS, SKIPPED, FILTERED, FAILED, EXHAUSTED, DEFERRED, UNPROCESSED), `ProcessingResult` factories, and `ProcessingContext` (uses `RunMode` for mode). | `typing` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `UnifiedProcessor.process()` | `agent_config/{workflow}.yml` | Reads | `actions[].guard`, `actions[].granularity`, `actions[].kind` |
| `TaskPreparer.prepare()` | `agent_config/{workflow}.yml` | Reads | `actions[].guard`, `actions[].conditional_clause` |
| `ResultCollector.collect()` | `agent_io/target/{action}/` | Writes | — |
| `EnrichmentPipeline.enrich()` | `agent_io/target/{action}/` | Transforms | — |
| `BatchContextAdapter.to_processing_context()` | `agent_io/staging/` | Reads | — |
| `ExhaustedRecordBuilder.build_empty_content()` | `schema/{workflow}/{action}.yml` | Reads | `actions[].schema` |
| `ProcessorErrorHandlerMixin.load_file()` | `agent_io/staging/` | Reads | — |

**Internal only**: `ProcessingStatus`, `ProcessingResult`, `ProcessingContext`, `GuardStatus`, `PreparedTask`, `PreparationContext`, `RetryState`, `RetryMetadata`, `RepromptMetadata`, `RecoveryMetadata`, `CollectionStats` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `llm` | inbound | Batch and online runners delegate to UnifiedProcessor |
| `prompt` | inbound | DataGenerator uses OnlineLLMStrategy for subsequent-stage processing |
| `workflow` | inbound | Pipeline orchestrator calls processing for each action stage |
| `prompt` | outbound | TaskPreparer uses PromptPreparationService for context and prompt rendering |
| `input` | outbound | Uses guard evaluators and field resolution from preprocessing |
| `output` | outbound | Uses ResponseSchemaCompiler for schema validation during reprompt |
| `storage` | outbound | ResultCollector writes dispositions to StorageBackend |
| `config` | outbound | Reads action configuration types and run mode from config |

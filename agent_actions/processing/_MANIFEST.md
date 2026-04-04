# Processing Manifest

## Overview

Shared processing utilities used by batch/online runners: enrichment, error handling,
lineage helpers, recovery flows, and transformation pipelines.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [invocation](invocation/) | LLM invocation strategies (online/batch) for unified execution. |
| [recovery](recovery/_MANIFEST.md) | Retry, checkpoint, and recovery helpers for failed batches. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_context_adapter.py` | Module | Adapts batch state to `ProcessingContext` + `ProcessingResult` for the shared `EnrichmentPipeline`. | `batch`, `enrichment` |
| `enrichment.py` | Module | Adds metadata (timestamps, run IDs) to processed items. | `logging`, `workflow` |
| `error_handling.py` | Module | `ProcessorErrorHandlerMixin` for wrapping file loading/processing logic. | `logging` |
| `exhausted_builder.py` | Module | Builds reports once a workflow’s retries are exhausted. | `validation`, `logging` |
| `helpers.py` | Module | Shared helpers (UUID construction, tuple flattening) for processors. | `processing` |
| `processor.py` | Module | Base processor that glues loaders, transformers, and error handling. | `input`, `processing` |
| `result_collector.py` | Module | Collects main vs side outputs, handles duplicates. Counts UNPROCESSED results separately from successes. | `output` |
| `prepared_task.py` | Module | `GuardStatus` enum (PASSED, SKIPPED, FILTERED, UPSTREAM_UNPROCESSED), `PreparedTask` dataclass, and `PreparationContext` (carries `mode: RunMode` directly). | `typing` |
| `task_preparer.py` | Module | Unified task preparation (normalize, prompt, guard) for batch/online. Short-circuits upstream-unprocessed records before context loading. | `input`, `prompt` |
| `types.py` | Module | `ProcessingStatus` enum (SUCCESS, SKIPPED, FILTERED, FAILED, EXHAUSTED, DEFERRED, UNPROCESSED), `ProcessingResult` factories, and `ProcessingContext` (uses `RunMode` for mode). | `typing` |

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `RecordProcessor.__init__()` | — | Reads | `actions[].granularity`, `actions[].kind` |
| `RecordProcessor.process()` | `agent_io/target/{action}/` | Transforms | — |
| `TaskPreparer.prepare()` | — | Reads | `actions[].guard`, `actions[].conditional_clause` |
| `TaskPreparer._render_prompt()` | `prompt_store/{workflow}.md` | Reads | `actions[].prompt` |
| `ResultCollector.collect()` | `agent_io/target/{action}/` | Writes | — |
| `EnrichmentPipeline.enrich()` | `agent_io/target/{action}/` | Transforms | — |
| `OnlineStrategy.invoke()` | — | Transforms | `actions[].retry`, `actions[].reprompt` |
| `BatchContextAdapter.to_processing_context()` | — | Reads | `actions[].agent_type` |
| `UdfValidator.__init__()` | `tools/shared/reprompt_validations.py` | Reads | `actions[].reprompt.validation` |
| `ResponseValidator.validate()` | — | Validates | `actions[].reprompt.validation` |
| `ExhaustedRecordBuilder` | `agent_io/target/{action}/` | Writes | `actions[].retry.max_attempts` |

**Internal only**: `ProcessingStatus`, `ProcessingResult`, `ProcessingContext`, `PreparedTask`, `GuardStatus`, `PreparationContext`, `RecoveryMetadata`, `RetryMetadata`, `RepromptMetadata`, `RetryState`, `InvocationResult`, `InvocationStrategy`, `InvocationStrategyFactory`, `BatchProvider`, `LineageEnricher`, `MetadataEnricher`, `VersionIdEnricher`, `PassthroughEnricher`, `RequiredFieldsEnricher`, `RecoveryEnricher`, `helpers`, `error_handling` — no direct project surface.

**Examples** — see this module in action:
- [`examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml`](../../examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml) — workflow using `retry` with `max_attempts`, `reprompt` with `validation` and `on_exhausted`, guards with `condition` / `on_false`, and `granularity: Record`
- [`examples/review_analyzer/tools/shared/reprompt_validations.py`](../../examples/review_analyzer/tools/shared/reprompt_validations.py) — `@reprompt_validation` UDF loaded by `UdfValidator` at runtime for response validation
- [`examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml`](../../examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml) — FILE granularity tool actions demonstrating the map-reduce processing pattern with `version_consumption`
- [`examples/incident_triage/tools/shared/reprompt_validations.py`](../../examples/incident_triage/tools/shared/reprompt_validations.py) — shared reprompt validation UDF used across multiple actions in the triage workflow

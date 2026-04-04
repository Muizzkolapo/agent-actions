# Validation Manifest

## Overview

Validators guard every CLI command and runtime operation—from agent config
decoders to schema validators and preflight checks.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [action_validators](action_validators/_MANIFEST.md) | Reusable action validation rules shared across commands. |
| [orchestration](orchestration/_MANIFEST.md) | Workflow/runner-specific validation helpers. |
| [preflight](preflight/_MANIFEST.md) | Validators executed before workflows run (vendors, prompts, pipelines). |
| [static_analyzer](static_analyzer/_MANIFEST.md) | Core static analysis: data flow graphs, type checking, field analysis. |
| [utils](utils/_MANIFEST.md) | Helper utilities (UDF validation, path checks, etc.). |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base_validator.py` | Module | `BaseValidator` base class with helper assertions for validators. | `validation` |
| `batch_validator.py` | Module | Validator that ensures batch CLI arguments conform to expectations. | `validation`, `llm.batch` |
| `clean_validator.py` | Module | `CleanCommandArgs` pydantic model used by the CLI. | `validation` |
| `config_validator.py` | Module | Central config parser/validator used across startup flows. | `configuration`, `validation` |
| `init_validator.py` | Module | `InitCommandArgs` pydantic model used by the CLI. | `validation` |
| `path_validator.py` | Module | Path validation utilities conforming to BaseValidator interface. | `validation` |
| `prompt_ast.py` | Module | Jinja2 AST parser for extracting template variables. | `prompt_generation` |
| `prompt_validator.py` | Module | Validates prompt references during CLI operations. | `validation` |
| `render_validator.py` | Module | `RenderCommandArgs` pydantic model. | `validation` |
| `run_validator.py` | Module | `RunCommandArgs` and pre-flight gating. | `validation` |
| `schema_output_validator.py` | Module | Validates output data against JSON schemas. | `validation`, `schema` |
| `schema_validator.py` | Module | `SchemaValidator`: validates schema files against JSON Schema meta-schema. Fires a single `ValidationStartEvent` via the base class `_prepare_validation()`; the redundant `DataValidationStartedEvent` at the top of `validate()` has been removed. | `validation` |
| `status_validator.py` | Module | `StatusCommandArgs` definition. | `validation` |
| `validate_udfs.py` | Module | Validates that UDFs referenced in configs exist. | `utils.udf_management`, `validation` |

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `ConfigValidator.validate()` | `agent_config/{workflow}/{workflow}.yml` | Validates | `actions[]` entries, `dependencies`, `is_operational` |
| `ConfigValidator._check_agent_name_unique_logic()` | `agent_config/{workflow}/{workflow}.yml` | Validates | file stem must match workflow name |
| `SchemaValidator.validate()` | `schema/{workflow}/{action}.yml` | Validates | JSON Schema structure, meta-schema compliance |
| `SchemaValidator._process_schema_file()` | `schema/{workflow}/{action}.yml` | Reads | `type`, `properties`, `required`, `fields` |
| `validate_output_against_schema()` | `schema/{workflow}/{action}.yml` | Validates | LLM output checked against schema `properties`, `required`, `fields` |
| `PromptValidator.validate()` | `prompt_store/{workflow}.md` | Validates | prompt ID uniqueness, block structure, file size |
| `PathValidator.validate()` | `{workflow}/agent_config/`, `{workflow}/agent_io/` | Validates | directory existence, readability, writability |
| `ValidateUDFsCommand.validate()` | `agent_config/{workflow}/{workflow}.yml` | Reads | `actions[].impl` references |
| `ValidateUDFsCommand.validate()` | `tools/{workflow}/` | Validates | UDF `@udf_tool` functions match `impl` references |
| `RunCommandArgs` | — | Validates | CLI `--agent`, `--user-code`, `--execution-mode` arguments |
| `BaseValidator._prepare_validation()` | — | — | fires `ValidationStartEvent`/`ValidationCompleteEvent` for all validators |

**Internal only**: `base_validator.py` (base class), `batch_validator.py` / `clean_validator.py` / `init_validator.py` / `render_validator.py` / `status_validator.py` (CLI argument models), `prompt_ast.py` (Jinja2 AST internals) -- consumed by other validators or CLI, no direct project file surface.

**Examples** -- see this module in action:
- [`examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_config/book_catalog_enrichment.yml`](../../examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_config/book_catalog_enrichment.yml) -- validated by `ConfigValidator`; exercises action entry validation, dependency checks, circular dependency detection
- [`examples/book_catalog_enrichment/schema/book_catalog_enrichment/review_classification.yml`](../../examples/book_catalog_enrichment/schema/book_catalog_enrichment/review_classification.yml) -- fields-format schema validated by `SchemaValidator._is_fields_format()`; also exercised by `validate_output_against_schema()` at runtime
- [`examples/book_catalog_enrichment/prompt_store/book_catalog_enrichment.md`](../../examples/book_catalog_enrichment/prompt_store/book_catalog_enrichment.md) -- prompt file validated by `PromptValidator` for ID uniqueness and block structure
- [`examples/book_catalog_enrichment/tools/book_catalog_enrichment/format_catalog_entry.py`](../../examples/book_catalog_enrichment/tools/book_catalog_enrichment/format_catalog_entry.py) -- UDF tool discovered by `ValidateUDFsCommand`, matched against `actions[].impl` in workflow config
- [`examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml`](../../examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml) -- `ConfigValidator` validates guard expressions (`actions[].guard.condition`), version config, and cross-action dependency graph
- [`examples/incident_triage/schema/incident_triage/classify_severity.yml`](../../examples/incident_triage/schema/incident_triage/classify_severity.yml) -- schema validated by `SchemaValidator` for JSON Schema correctness
- [`examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml`](../../examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml) -- exercises `ConfigValidator` with guard conditions (`consensus_score >= 6`), version consumption, and multi-vendor model selection

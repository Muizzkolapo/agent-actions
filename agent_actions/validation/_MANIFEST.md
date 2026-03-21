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

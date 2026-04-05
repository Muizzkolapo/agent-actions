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
| `project_validator.py` | Module | `ProjectValidator` for project name, directory, and template validation. | `validation` |
| `run_validator.py` | Module | `RunCommandArgs` pydantic model and pre-flight gating. | `validation` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `ConfigValidator.validate` | `agent_config/{workflow}.yml` | Validates | `agent_type`, `dependencies`, `is_operational` |
| `SchemaValidator.validate` | `schema/{workflow}/{action}.yml` | Validates | `type`, `properties`, `required`, `items` |
| `PromptValidator.validate` | `prompt_store/{workflow}.md` | Validates | — |
| `PathValidator.validate` | `agent_io/staging/` | Validates | — |
| `PathValidator.validate` | `agent_io/target/{action}/` | Validates | — |
| `validate_output_against_schema` | `schema/{workflow}/{action}.yml` | Validates | `fields`, `properties`, `required` |
| `validate_and_raise_if_invalid` | `schema/{workflow}/{action}.yml` | Validates | `fields`, `properties`, `required` |
| `PromptASTAnalyzer.extract_variables` | `prompt_store/{workflow}.md` | Reads | — |
| `ValidateUDFsCommand.validate` | `agent_config/{workflow}.yml` | Validates | `impl` |
| `ValidateUDFsCommand.validate` | `tools/{workflow}/*.py` | Validates | — |
| `ProjectValidator.validate` | `agent_actions.yml` | Validates | `project_name` |

**Internal only**: `BaseValidator`, `PathValidationOptions`, `BatchCommandArgs`, `CleanCommandArgs`, `InitCommandArgs`, `RenderCommandArgs`, `RunCommandArgs`, `StatusCommandArgs`, `SchemaValidationReport`, `FieldUsage`, `scan_prompt_fields_ast`, `validate_prompt_fields_ast` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `agent_actions/config` | outbound | Reads config models (`ConfigManager`, `PathManager`, `ProjectPathsFactory`, `PromptDefaults`). |
| `agent_actions/errors` | outbound | Raises `SchemaValidationError`, `ConfigurationError`, `FileLoadError`, error types for UDF validation. |
| `agent_actions/logging` | outbound | Fires validation events (`ValidationStartEvent`, `ValidationCompleteEvent`, etc.) via `fire_event`. |
| `agent_actions/output` | outbound | Uses `config_fields.get_default` and `ActionExpander` via `ConfigManager`. |
| `agent_actions/prompt` | outbound | Uses `PromptLoader` for prompt ID extraction. |
| `agent_actions/input` | outbound | `ValidateUDFsCommand` uses `discover_udfs` / `validate_udf_references`. |
| `agent_actions/utils` | outbound | Uses `FileHandler`, `constants`, `udf_management.registry`. |
| `agent_actions/workflow` | inbound | Workflow execution calls validators before running actions. |
| `agent_actions/cli` | inbound | CLI commands invoke validators for pre-flight checks. |
| `pydantic` | outbound | Command args models and validation. |
| `jinja2` | outbound | `PromptASTAnalyzer` uses Jinja2 AST parsing. |
| `jsonschema` | outbound | `SchemaValidator` validates against JSON Schema meta-schema. |

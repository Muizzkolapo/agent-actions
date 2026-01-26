# Validation Manifest

## Overview

Validators guard every CLI command and runtime operation—from agent config
decoders to schema validators and preflight checks.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [agent](agent/_MANIFEST.md) | Helpers that validate agent-specific configuration blocks. |
| [agent_validators](agent_validators/_MANIFEST.md) | Reusable agent validation rules shared across commands. |
| [orchestration](orchestration/_MANIFEST.md) | Workflow/runner-specific validation helpers. |
| [preflight](preflight/_MANIFEST.md) | Validators executed before workflows run (vendors, prompts, pipelines). |
| [static_analysis](static_analysis/_MANIFEST.md) | Static field-usage and schema analysis utilities. |
| [utils](utils/_MANIFEST.md) | Helper utilities (UDF validation, path checks, etc.). |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base.py` | Module | Core validator helpers (issue reporting, base classes). | `logging` |
| `base_validator.py` | Module | `ValidationBase` with helper assertions for CLI arguments. | `validation` |
| `batch.py` | Module | Batch-specific guards (batch size, parallelism). | `llm.batch` |
| `batch_validator.py` | Module | Validator that ensures batch CLI arguments conform to expectations. | `validation`, `llm.batch` |
| `clean.py` | Module | Validator for the `clean` CLI command arguments. | `cli`, `validation` |
| `clean_validator.py` | Module | `CleanCommandArgs` pydantic model used by the CLI. | `validation` |
| `config.py` | Module | Validates `agent_actions.yml` and environment overrides. | `file_io` |
| `config_validator.py` | Module | Central config parser/validator used across startup flows. | `configuration`, `validation` |
| `directory.py` | Module | Directory/structure validators (path, hierarchy). | `file_io` |
| `directory_validator.py` | Module | Ensures directories exist and enforce fixture conventions. | `validation` |
| `docs.py` | Module | Validates docs CLI options and prompts before generation. | `tooling.docs`, `validation` |
| `docs_validator.py` | Module | CLI validator for `agac docs` commands. | `validation` |
| `init.py` | Module | Project initialization validation helpers. | `configuration`, `validation` |
| `init_validator.py` | Module | `InitCommandArgs` pydantic model used by the CLI. | `validation` |
| `prompt.py` | Module | Prompt-level validation (tokenization, context). | `prompt_generation`, `validation` |
| `prompt_validator.py` | Module | Validates prompt references during CLI operations. | `validation` |
| `render.py` | Module | Validates render/compile command arguments. | `validation` |
| `render_validator.py` | Module | `RenderCommandArgs` pydantic model. | `validation` |
| `run.py` | Module | Workflow run pre-flight validator orchestration entrypoints. | `workflow`, `validation` |
| `run_validator.py` | Module | `RunCommandArgs` and pre-flight gating. | `validation` |
| `schema.py` | Module | Schema command validators (exists, format). | `validation`, `schema` |
| `schema_validator.py` | Module | Pydantic model for schema command options. | `validation` |
| `startup.py` | Module | Validation performed when the agent-actions process starts. | `logging`, `validation` |
| `startup_validator.py` | Module | Validator used during environment bootstrap. | `validation` |
| `status.py` | Module | Validates `status` CLI arguments. | `validation` |
| `status_validator.py` | Module | `StatusCommandArgs` definition. | `validation` |
| `validate_udfs.py` | Module | Validates that UDFs referenced in configs exist. | `utils.udf_management`, `validation` |

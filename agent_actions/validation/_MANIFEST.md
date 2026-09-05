# Validation Manifest

**[> Architecture Deep Dive (ARCHITECTURE.md)](ARCHITECTURE.md)** -- Three validation phases, data flow, caveats.

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
| `bus_namespace_validator.py` | Module | `find_unknown_bus_namespaces`: AST scan flagging tool-UDF reads of `data.get("X")` / `data["X"]` where X is not a runtime bus namespace (action name or framework key), catching silent namespace typos at `validate-udfs`. | `validation` |
| `config_validator.py` | Module | Central config parser/validator used across startup flows. | `configuration`, `validation` |
| `dag_schema_fit_validator.py` | Module | `find_dag_schema_compatibility_gaps`: per producer/consumer edge in the workflow DAG, reports `{consumer: [missing fields]}` where a tool consumer's required output field is neither guaranteed at any position in an upstream producer's compiled schema nor declared as synthesized via `defaults:` on the action; `DAG_FIT_REMEDY` carries the shared fix text. Symmetric two-level descent on both sides (root, `field.`, `field[].`); fields the consuming UDF provably emits are excluded via the `synthesized` argument the preflight service supplies. Wired at `PreflightService._warn_dag_schema_compatibility_gaps` (spec 592 Phase 2, warn-only). | `validation` |
| `dep_observe_validator.py` | Module | `find_missing_observe_deps`: preflight mirror of the fatal runtime check that every declared dependency has an observe/passthrough field reference. | `validation` |
| `expectations_validator.py` | Module | Refuses preflight, via `find_expectation_defects`, when an action's `expect:` block (inline `expectations:` list, named `suite:` reference, or a bare block that defaults to the action's own schema) names an unregistered type, an unaccepted parameter, a missing required parameter, a superseded spelling, or a `field:` selector the action's output cannot produce. It builds each suite the way the runner does, so rules declared on a schema's fields are validated too. Also checks `llm_judge`-specific parameters: a non-positive-integer `votes:`, and a `context:` value that is not a list, names an unknown action, or names a field that action does not produce (checked against the full per-action `available_fields` map, not just the current action). For inline `expectations:`, a malformed `context:` ref is often caught earlier by the pre-existing `context_scope.observe` static-type validator instead, since a judged expectation's `context:` refs are auto-injected into `observe:` — this validator remains the only check for named `suite:` mode (which never auto-injects) and for a non-list `context:` value (which never reaches `observe:` at all). Wired at `PreflightService._check_expectation_defects`. | `validation` |
| `path_validator.py` | Module | Path validation utilities conforming to BaseValidator interface. | `validation` |
| `prompt_ast.py` | Module | Jinja2 AST parser for extracting template variables. | `prompt_generation` |
| `prompt_validator.py` | Module | Validates prompt references during CLI operations. | `validation` |
| `schema_output_validator.py` | Module | Validates output data against JSON schemas. | `validation`, `schema` |
| `schema_validator.py` | Module | `SchemaValidator`: validates schema files against JSON Schema meta-schema. Fires a single `ValidationStartEvent` via the base class `_prepare_validation()`; the redundant `DataValidationStartedEvent` at the top of `validate()` has been removed. | `validation` |
| `udf_passthrough_validator.py` | Module | `find_passthrough_schema_risks`: static AST scan flagging `kind:tool` UDFs that return bus-derived dicts under a strict output schema. | `validation` |
| `udf_required_field_validator.py` | Module | `find_conditional_required_field_risks`: static AST scan that refuses preflight when a `kind:tool` UDF's required output-schema fields are only produced inside a conditional branch (post-568 required-by-default class; refusal wired in `PreflightService._check_tool_conditional_required_field_risks`). | `validation` |
| `validate_udfs.py` | Module | Validates that UDFs referenced in configs exist. | `utils.udf_management`, `validation` |
| `project_validator.py` | Module | `ProjectValidator` for project name, directory, and template validation. | `validation` |

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

**Internal only**: `BaseValidator`, `PathValidationOptions`, `SchemaValidationReport`, `FieldUsage`, `scan_prompt_fields_ast`, `validate_prompt_fields_ast` -- no direct project surface.

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

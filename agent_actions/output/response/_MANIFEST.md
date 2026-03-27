# Response Manifest

## Overview

Response helpers include schema loaders, guard parsers, and config/field types that
Normalize outputs (for docs, CLI, and exporters) with consistent metadata.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config_fields.py` | Module | Field helpers used by schema configuration objects. `SIMPLE_CONFIG_FIELDS` includes runtime fields for standard 3-level inheritance. | `output.response.schema`, `validation` |
| `config_schema.py` | Module | Schema definitions for response metadata configuration. | `validation` |
| `consolidated_guard.py` | Shim | Re-export shim → `guards.consolidated_guard`. | `guards` |
| `expander.py` | Module | Facade: `ActionExpander` class orchestrates action-to-agent expansion, delegates to submodules. | `tooling.docs`, `schema` |
| `expander_validation.py` | Module | Validation functions: vendor, action name, required fields. | `validation` |
| `expander_schema.py` | Module | Schema processing: template replacement, output schema compilation. | `schema`, `validation` |
| `expander_action_types.py` | Module | Action-type processors: guard config, tool actions, HITL actions. | `validation`, `guards` |
| `expander_merge.py` | Module | Config merge/init: directive merging, context_scope, chunk config, optional fields. | `config` |
| `expander_guard_validation.py` | Module | Guard reference validation: schema registry, upstream reference checks. | `validation`, `guards` |
| `guard_parser.py` | Shim | Re-export shim → `guards.guard_parser`. | `guards` |
| `loader.py` | Module | `SchemaLoader` that reads and constructs schemas from YAML files or inline definitions. `load_schema` accepts `project_root: Path \| None`. | `file_io`, `validation` |
| `schema_conversion.py` | Module | Schema format conversion: `_convert_json_schema_to_unified`, `compile_field`. | `validation` |
| `vendor_compilation.py` | Module | Vendor-specific schema compilation: `compile_unified_schema` for OpenAI, Anthropic, Gemini, Ollama, etc. | `validation`, `schema_conversion` |
| `dispatch_injection.py` | Module | Dispatch/injection logic: `_inject_functions_into_schema`, `_resolve_dispatch_in_schema`. | `prompt` |
| `context_data.py` | Module | Context data handling and schema loading helpers: `_prepare_context_data_str`, `_load_inline_schema`, `_load_named_schema`, `_unwrap_nested_schema`, `_compile_schema_for_vendor`. | `schema_loader`, `vendor_compilation`, `dispatch_injection` |
| `response_builder.py` | Module | `ResponseBuilder` — unified output-field wrapping and usage extraction for all LLM providers. `UsageResult`, `ProviderResponseConfig`, `PROVIDER_RESPONSE_CONFIGS` registry. | `llm`, `output` |
| `schema.py` | Module | `ResponseSchemaCompiler` service class. Compiles action response schemas into vendor-specific LLM formats. Delegates to `schema_conversion`, `vendor_compilation`, `dispatch_injection`, `context_data`. | `validation`, `schema_loader` |

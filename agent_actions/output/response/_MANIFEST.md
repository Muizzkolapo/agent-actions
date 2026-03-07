# Response Manifest

## Overview

Response helpers include schema loaders, guard parsers, and config/field types that
Normalize outputs (for docs, CLI, and exporters) with consistent metadata.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config_fields.py` | Module | Field helpers used by schema configuration objects. | `output.response.schema`, `validation` |
| `config_schema.py` | Module | Schema definitions for response metadata configuration. | `validation` |
| `consolidated_guard.py` | Module | Renders consolidated guard results with metadata for outputs. | `validation`, `logging` |
| `expander.py` | Module | Facade: `ActionExpander` class orchestrates action-to-agent expansion, delegates to submodules. | `tooling.docs`, `schema` |
| `expander_validation.py` | Module | Validation functions: vendor, action name, required fields. | `validation` |
| `expander_schema.py` | Module | Schema processing: template replacement, output schema compilation. | `schema`, `validation` |
| `expander_action_types.py` | Module | Action-type processors: guard config, tool actions, HITL actions. | `validation`, `guards` |
| `expander_merge.py` | Module | Config merge/init: directive merging, context_scope, chunk config, optional fields. | `config` |
| `expander_guard_validation.py` | Module | Guard reference validation: schema registry, upstream reference checks. | `validation`, `guards` |
| `guard_parser.py` | Module | Parses guard metadata from response payloads. | `preprocessing` |
| `loader.py` | Module | `SchemaLoader` that reads and validates schema files from YAML. | `file_io`, `validation` |
| `schema.py` | Module | Schema utilities used by the CLI and docs to describe workflow outputs. | `validation`, `schema_loader` |

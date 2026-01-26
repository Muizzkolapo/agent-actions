# Response Manifest

## Overview

Response helpers include schema loaders, guard parsers, and config/field types that
Normalize outputs (for docs, CLI, and exporters) with consistent metadata.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config_fields.py` | Module | Field helpers used by schema configuration objects. | `output.response.schema`, `validation` |
| `config_schema.py` | Module | Schema definitions for response metadata configuration. | `validation` |
| `config_types.py` | Module | Typed dictionaries and `AgentEntryDict` helpers for response loading. | `config` |
| `consolidated_guard.py` | Module | Renders consolidated guard results with metadata for outputs. | `validation`, `logging` |
| `expander.py` | Module | Expands inline schema definitions and prompts when rendering docs. | `tooling.docs`, `schema` |
| `guard_parser.py` | Module | Parses guard metadata from response payloads. | `preprocessing` |
| `loader.py` | Module | `SchemaLoader` that reads schema files, caches them, and surfaces type information. | `file_io`, `validation` |
| `schema.py` | Module | Schema utilities used by the CLI and docs to describe workflow outputs. | `validation`, `schema_loader` |

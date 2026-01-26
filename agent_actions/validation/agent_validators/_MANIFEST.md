# Agent Validators Manifest

## Overview

Agent-level validators enforce schema conformity, vendor compatibility, and field
requirements before workflows execute.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `agent_entry_structure_validator.py` | Module | Ensures agent configs adhere to the expected dict structure. | `validation` |
| `agent_required_fields_validator.py` | Module | Validates that required keys (prompt, schema, intent) exist. | `validation` |
| `agent_type_specific_validator.py` | Module | Applies vendor-specific checks depending on agent type. | `llm.providers`, `validation` |
| `base_agent_validator.py` | Module | Base class shared by agent validators. | `validation` |
| `batch_mode_compatibility_validator.py` | Module | Ensures batch mode parameters (chunking, concurrency) are compatible. | `llm.batch`, `validation` |
| `granularity_output_field_validator.py` | Module | Verifies output fields align with configured granularity. | `validation`, `output` |
| `inline_schema_validator.py` | Module | Validates inline schemas defined inside agent configs. | `validation`, `schema` |
| `optional_field_type_validator.py` | Module | Checks optional fields for supported types. | `validation` |
| `unknown_keys_detector.py` | Module | Warns about unsupported keys in agent definitions. | `validation` |
| `vendor_compatibility_validator.py` | Module | Validates vendor-specific limits (OpenAI, Anthropic, etc.). | `llm.providers`, `validation` |

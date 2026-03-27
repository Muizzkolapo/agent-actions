# Action Validators Manifest

## Overview

Action-level validators enforce schema conformity, vendor compatibility, and field
requirements before workflows execute.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `action_entry_structure_validator.py` | Module | Ensures action configs adhere to the expected dict structure. | `validation` |
| `action_required_fields_validator.py` | Module | Validates that required keys (prompt, schema, intent) exist. | `validation` |
| `action_type_specific_validator.py` | Module | Applies vendor-specific checks depending on agent type. | `llm.providers`, `validation` |
| `base_action_validator.py` | Module | Base class shared by action validators. | `validation` |
| `granularity_output_field_validator.py` | Module | Verifies output fields align with configured granularity. | `validation`, `output` |
| `inline_schema_validator.py` | Module | Validates inline schemas defined inside action configs. | `validation`, `schema` |
| `optional_field_type_validator.py` | Module | Checks optional fields for supported types. | `validation` |
| `unknown_keys_detector.py` | Module | Warns about unsupported keys in action definitions. | `validation` |
| `vendor_compatibility_validator.py` | Module | Validates vendor-specific limits (OpenAI, Anthropic, etc.). | `llm.providers`, `validation` |

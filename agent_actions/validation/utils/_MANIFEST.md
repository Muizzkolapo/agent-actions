# Utils Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `agent_config_validation_utilities.py` | Module | Shared utilities for agent configuration validation. | `utilities` |
| `AgentConfigValidationUtilities` | Class | Centralized utilities for agent configuration validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `normalize_entry_keys_to_lowercase` | Method | Convert all dictionary keys to lowercase for case-insensitive comparison. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_case_insensitive_value` | Method | Get value from dict using case-insensitive key lookup. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_validation_context` | Method | Format a standardized description for error messages. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_required_agent_keys` | Method | Get set of required agent configuration keys. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_optional_agent_keys` | Method | Get set of optional agent configuration keys. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_type_specific_keys` | Method | Get required keys for a specific agent type. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_all_known_agent_keys` | Method | Get all known agent keys (required + optional + type-specific). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_valid_batch_vendors` | Method | Get set of valid batch processing vendors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_valid_granularity_values` | Method | Get set of valid granularity values. | - |
| `schema_type_validator.py` | Module | Utility for validating schema type strings. | - |
| `SchemaTypeValidator` | Class | Validates schema type strings for agent configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_valid` | Method | Check if validator is properly configured. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_valid_schema_type` | Method | Check if a schema type string is valid. | - |

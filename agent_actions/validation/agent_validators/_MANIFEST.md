# Agent Validators Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `agent_entry_structure_validator.py` | Module | Validator for agent entry basic structure. | `validation` |
| `AgentEntryStructureValidator` | Class | Validates that agent entry has valid basic structure. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate agent entry is a dictionary. | - |
| `agent_required_fields_validator.py` | Module | Validator for required agent configuration fields. | `validation` |
| `AgentRequiredFieldsValidator` | Class | Validates that all required agent fields are present. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Check that all required fields are present in entry. | - |
| `agent_type_specific_validator.py` | Module | Validator for agent type and type-specific configuration requirements. | `validation` |
| `AgentTypeSpecificValidator` | Class | Validates agent type field and type-specific requirements. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate agent type and type-specific requirements. | - |
| `base_agent_validator.py` | Module | Base class for agent entry validators. | - |
| `AgentEntryValidationResult` | Class | Result from a single validator execution. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `success` | Method | Create a success result (no errors/warnings). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `critical_failure` | Method | Create a critical failure result that stops validation chain. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `with_errors` | Method | Create a result with errors (but not critical). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `with_warnings` | Method | Create a result with warnings only. | - |
| `BaseAgentEntryValidator` | Class | Abstract base class for all agent entry validators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_valid` | Method | Check if validator is properly configured. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Perform validation on the agent entry. | - |
| `batch_mode_compatibility_validator.py` | Module | Backward compatibility module for batch mode compatibility validator. | `validation` |
| `granularity_output_field_validator.py` | Module | Validator for granularity and output_field configuration. | `utilities`, `validation` |
| `GranularityAndOutputFieldValidator` | Class | Validates granularity enum and output_field compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate granularity and output_field configuration. | - |
| `inline_schema_validator.py` | Module | Validator for inline schema configuration. | `utilities`, `validation` |
| `InlineSchemaValidator` | Class | Validates inline schema configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate inline schema configuration. | - |
| `optional_field_type_validator.py` | Module | Validator for optional field types in agent configuration. | `utilities`, `validation` |
| `OptionalFieldTypeValidator` | Class | Validates types of optional configuration fields. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate optional field types. | - |
| `unknown_keys_detector.py` | Module | Detector for unknown/unexpected keys in agent configuration. | `validation` |
| `UnknownKeysDetector` | Class | Detects unknown or unexpected keys in agent configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Detect unknown keys in agent configuration. | - |
| `vendor_compatibility_validator.py` | Module | Validator for vendor compatibility across batch and online modes. | `validation` |
| `VendorCompatibilityValidator` | Class | Validates vendor compatibility for batch and online modes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate vendor compatibility based on run_mode. | - |

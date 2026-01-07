# Preflight Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context_structure_validator.py` | Module | Context structure validator for pre-flight validation. | `validation` |
| `ContextStructureValidator` | Class | Validates that context data has the expected structure and fields. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate context structure against expected schema. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_context` | Method | Convenience method to validate context directly. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_issues` | Method | Get the list of validation issues found. | - |
| `dependency_validator.py` | Module | Dependency validator for pre-flight validation. | `validation` |
| `DependencyValidator` | Class | Validates agent dependencies for circular references and missing agents. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate dependencies in workflow configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_workflow` | Method | Convenience method to validate workflow dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_dependency_order` | Method | Get topological sort of agents (execution order). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_issues` | Method | Get the list of validation issues found. | - |
| `error_formatter.py` | Module | Unified error formatter for pre-flight validation. | - |
| `ValidationIssue` | Class | Represents a single validation issue (error or warning). | - |
| `PreFlightErrorFormatter` | Class | Formats pre-flight validation errors consistently. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_issue` | Method | Format a single validation issue into a user-friendly string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_issues` | Method | Format multiple validation issues into a summary string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_template_variable_issue` | Method | Create a validation issue for missing template variables. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_context_structure_issue` | Method | Create a validation issue for context structure mismatch. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_dependency_issue` | Method | Create a validation issue for dependency problems. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_vendor_config_issue` | Method | Create a validation issue for vendor configuration problems. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_path_issue` | Method | Create a validation issue for invalid paths. | - |
| `path_validator.py` | Module | Path validator for pre-flight validation. | `validation` |
| `PathValidator` | Class | Validates file and directory paths exist and are accessible. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate paths in the provided configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_paths` | Method | Convenience method to validate paths directly. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_agent_paths` | Method | Validate all paths referenced in agent configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_issues` | Method | Get the list of validation issues found. | - |
| `preflight_validator.py` | Module | Pre-flight validation orchestrator. | `errors`, `validation` |
| `PreFlightValidationResult` | Class | Result of pre-flight validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_message` | Method | Format the validation result as a user-friendly message. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `raise_if_invalid` | Method | Raise PreFlightValidationError if validation failed. | - |
| `PreFlightValidator` | Class | Orchestrates pre-flight validation for both batch and online modes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Run all pre-flight validations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_for_batch` | Method | Convenience method for batch mode validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_for_online` | Method | Convenience method for online mode validation. | - |
| `validate_preflight` | Function | Convenience function for quick pre-flight validation. | - |
| `template_variable_validator.py` | Module | Template variable validator for pre-flight validation. | `validation` |
| `TemplateVariableValidator` | Class | Validates that Jinja2 template variables exist in the provided context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate template variables against provided context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_template_string` | Method | Convenience method to validate a template string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_issues` | Method | Get the list of validation issues found. | - |
| `vendor_compatibility_validator.py` | Module | Vendor compatibility validator for pre-flight validation. | `validation` |
| `VendorCompatibilityValidator` | Class | Validates vendor configuration and feature compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate vendor configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_vendor_config` | Method | Convenience method to validate vendor config directly. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_supported_vendors` | Method | Get set of supported vendor names. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_vendor_capabilities` | Method | Get capabilities for a specific vendor. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_issues` | Method | Get the list of validation issues found. | - |

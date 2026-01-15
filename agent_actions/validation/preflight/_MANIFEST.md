# Preflight Manifest

## Overview

The preflight package provides **runtime validation** for aspects that cannot be checked at compile-time, such as file existence and vendor API compatibility.

**Note:** Template variable validation, context structure validation, and dependency validation have been removed as they are now handled by the **Static Analyzer** at workflow load time. See `../DEPRECATION_TRACKER.md` for details.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `error_formatter.py` | Module | Unified error formatter for pre-flight validation. | - |
| `ValidationIssue` | Class | Represents a single validation issue (error or warning). | - |
| `PreFlightErrorFormatter` | Class | Formats pre-flight validation errors consistently. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_issue` | Method | Format a single validation issue into a user-friendly string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_issues` | Method | Format multiple validation issues into a summary string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_vendor_config_issue` | Method | Create a validation issue for vendor configuration problems. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_path_issue` | Method | Create a validation issue for invalid paths. | - |
| `path_validator.py` | Module | Path validator for pre-flight validation. | `validation` |
| `PathValidator` | Class | Validates file and directory paths exist and are accessible. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate paths in the provided configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_paths` | Method | Convenience method to validate paths directly. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_agent_paths` | Method | Validate all paths referenced in agent configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_issues` | Method | Get the list of validation issues found. | - |
| `vendor_compatibility_validator.py` | Module | Vendor compatibility validator for pre-flight validation. | `validation` |
| `VendorCompatibilityValidator` | Class | Validates vendor configuration and feature compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate vendor configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_vendor_config` | Method | Convenience method to validate vendor config directly. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_supported_vendors` | Method | Get set of supported vendor names. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_vendor_capabilities` | Method | Get capabilities for a specific vendor. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_issues` | Method | Get the list of validation issues found. | - |

## Removed Validators (2026-01-15)

The following validators have been removed as they are now redundant with static analyzer compile-time validation:

- ~~`template_variable_validator.py`~~ → Replaced by `WorkflowStaticAnalyzer`
- ~~`context_structure_validator.py`~~ → Replaced by `WorkflowStaticAnalyzer` + `context_scope`
- ~~`dependency_validator.py`~~ → Replaced by `DataFlowGraph` in `WorkflowStaticAnalyzer`
- ~~`preflight_validator.py`~~ → Orchestrator removed (all child validators redundant)

See `../DEPRECATION_TRACKER.md` for detailed rationale and migration guide.

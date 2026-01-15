# Validation Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [agent_validators](agent_validators/_MANIFEST.md) | Agent entry validators package. |
| [orchestration](orchestration/_MANIFEST.md) | Validation orchestration package. |
| [preflight](preflight/_MANIFEST.md) | Runtime validation for file paths and vendor compatibility. |
| [static_analyzer](static_analyzer/_MANIFEST.md) | Static workflow analysis for compile-time type checking. |
| [utils](utils/_MANIFEST.md) | Validation utilities package. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base_validator.py` | Module | Base validator class for all validation operations. | - |
| `BaseValidator` | Class | Unified base class for all validators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Performs the core validation logic for the specific validator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_error` | Method | Adds a validation error message to the internal list. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_warning` | Method | Adds a validation warning message to the internal list. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_errors` | Method | Returns a list of all validation errors recorded. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_warnings` | Method | Returns a list of all validation warnings recorded. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_errors` | Method | Clears all recorded validation errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_warnings` | Method | Clears all recorded validation warnings. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has_errors` | Method | Checks if any errors have been recorded during validation. | - |
| `batch_validator.py` | Module | Batch command validation module. | - |
| `BatchCommandArgs` | Class | Pydantic model for the batch command arguments. | - |
| `clean_validator.py` | Module | Clean command validation module. | - |
| `CleanCommandArgs` | Class | Pydantic model for the clean command arguments. | - |
| `config_validator.py` | Module | Configuration validator for agent configuration files. | `file_io`, `response_processing`, `validation` |
| `ConfigValidator` | Class | Validate agent configuration files with case-insensitive key handling. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Run validation based on the operation key in data. | - |
| `directory_validator.py` | Module | Directory validation utilities. | `validation` |
| `DirectoryValidator` | Class | Handles directory validation operations by inheriting from BaseValidator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validates directory-related operations. | - |
| `docs_validator.py` | Module | Docs command validation module. | - |
| `DocsCommandArgs` | Class | Pydantic model for the docs command arguments. | - |
| `init_validator.py` | Module | Init command validation module. | - |
| `InitCommandArgs` | Class | Pydantic model for the init command arguments. | - |
| `path_validator.py` | Module | Path validation utilities. | `cli`, `validation` |
| `PathValidationOptions` | Class | Options for path validation. | - |
| `PathValidator` | Class | Utility class for validating file and directory paths, | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validates file or directory paths based on the specified operation. | - |
| `project_validator.py` | Module | Project validation utilities. | `validation` |
| `ProjectValidator` | Class | Handles project validation operations by inheriting from BaseValidator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validates project creation parameters. | - |
| `prompt_ast_analyzer.py` | Module | Prompt Analysis using Jinja2 AST Parser (NO REGEX). | - |
| `FieldUsage` | Class | Information about how a field is used in the template. | - |
| `PromptASTAnalyzer` | Class | Analyzes Jinja2 templates using AST parsing (no regex). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_variables` | Method | Extract all variable references from a Jinja2 template using AST. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_referenced_variables` | Method | Extract both root variables and full paths. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_template_syntax` | Method | Validate Jinja2 template syntax. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `analyze_field_requirements` | Method | Analyze what fields are required and validate against available context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_detailed_field_usage` | Method | Get detailed information about how each field is used. | - |
| `scan_prompt_fields_ast` | Function | Quick utility to extract field references using AST (NO REGEX). | - |
| `validate_prompt_fields_ast` | Function | Validate prompt fields using AST parsing (NO REGEX). | - |
| `prompt_validator.py` | Module | Prompt validation utilities. | `validation` |
| `PromptValidator` | Class | Handles prompt validation operations by inheriting from BaseValidator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validates all prompt files in the specified directory. | - |
| `render_validator.py` | Module | Render command validation module. | - |
| `RenderCommandArgs` | Class | Pydantic model for the render command arguments. | - |
| `run_validator.py` | Module | Run command validation module. | - |
| `ExecutionMode` | Class | Execution mode for agent workflows. | - |
| `RunCommandArgs` | Class | Pydantic model for the run command arguments. | - |
| `schema_validator.py` | Module | Schema validation utilities. | `validation` |
| `SchemaValidator` | Class | Handles schema validation operations by inheriting from BaseValidator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validates schema files for a given agent in a specified directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_schema_compatibility` | Method | Validates that two schemas are compatible. | - |
| `startup_validator.py` | Module | Startup configuration validation for Agent Actions. | `errors`, `llm_invocation`, `state_management` |
| `StartupValidationError` | Class | Raised when startup validation fails. | - |
| `StartupValidator` | Class | Validates application configuration during startup. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_environment_variables` | Method | Validate required environment variables are present. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_file_system_access` | Method | Validate file system access permissions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_configuration_files` | Method | Validate configuration files can be loaded and parsed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_dependencies` | Method | Validate that required dependencies are available. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_performance_settings` | Method | Validate performance-related settings. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `run_full_validation` | Method | Run complete startup validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_validation_report` | Method | Get a detailed validation report. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `raise_on_errors` | Method | Raise StartupValidationError if there are validation errors. | - |
| `validate_startup` | Function | Convenience function to run startup validation. | - |
| `status_validator.py` | Module | Status command validation module. | - |
| `StatusCommandArgs` | Class | Pydantic model for the status command arguments. | - |
| `validate_udfs.py` | Module | validate-udfs command for the Agent Actions CLI. | `cli`, `errors`, `input_loading`, `llm_invocation`, `shared`, `utilities` |
| `ValidateUDFsCommand` | Class | Implementation of the validate-udfs command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Perform UDF validation and return the result. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the validate-udfs command with formatted CLI output. | - |
| `validate_udfs_cmd` | Function | Validate all UDF references in config without running the workflow. | - |

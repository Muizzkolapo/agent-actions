# Field Resolution Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `evaluation_context_provider.py` | Module | Service for building rich evaluation contexts for guards, filters, and prompts. | `utilities` |
| `ContextBuildConfig` | Class | Configuration for building evaluation context. | - |
| `EvaluationContext` | Class | Rich context for guard/filter/prompt evaluation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_action_output` | Method | Get output from a specific upstream action. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has_action` | Method | Check if an action's output exists in context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_field_value` | Method | Get a specific field from an action's output. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_flat_dict` | Method | Convert to flat dict for backward compatibility with WHERE clause evaluator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_nested_dict` | Method | Get the full nested structure (field_context). | - |
| `EvaluationContextProvider` | Class | Service for building rich evaluation contexts for guards, filters, and prompts. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_context` | Method | Build rich evaluation context for item-level operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_context_for_batch` | Method | Build context for batch mode (simplified parameters). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_minimal_context` | Method | Build minimal context without historical loading. | - |
| `exceptions.py` | Module | Custom exceptions for field resolution operations. | - |
| `FieldResolutionError` | Class | Base exception for all field resolution errors. | - |
| `InvalidReferenceError` | Class | Raised when a field reference has invalid syntax. | - |
| `ReferenceNotFoundError` | Class | Raised when a referenced action or field cannot be found in context. | - |
| `DependencyValidationError` | Class | Raised when a field reference violates dependency graph constraints. | - |
| `SchemaFieldValidationError` | Class | Raised when a field reference doesn't match the action's output schema. | - |
| `field_reference_resolver.py` | Module | Centralized service for parsing and resolving field references. | - |
| `ResolvedReference` | Class | Result of resolving a field reference. | - |
| `FieldReferenceResolver` | Class | Centralized service for parsing and resolving field references. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse` | Method | Parse a field reference string into structured format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_batch` | Method | Extract all field references from a text string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `resolve` | Method | Resolve a field reference to its value in the context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `resolve_batch` | Method | Resolve multiple references efficiently. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `substitute` | Method | Replace all field references in text with their resolved values. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_references` | Method | Validate that referenced actions exist in dependency graph. | - |
| `reference_parser.py` | Module | Unified parser for field references across different syntaxes. | - |
| `ReferenceFormat` | Class | Supported field reference formats. | - |
| `ParsedReference` | Class | Structured representation of a parsed field reference. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `field_name` | Method | Get the top-level field name (first element of path). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_nested` | Method | Check if this is a nested path reference (more than one level). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `full_path` | Method | Get full dotted path including action name. | - |
| `ReferenceParser` | Class | Unified parser for all field reference formats. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse` | Method | Parse a single field reference string into structured format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_batch` | Method | Extract all field references from a text string. | - |
| `reference_validator.py` | Module | Validates field references against the workflow dependency graph. | - |
| `ReferenceValidator` | Class | Validates field references against the workflow dependency graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate references against dependency graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_strict` | Method | Validate references and raise exception if invalid. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_and_validate` | Method | Extract references from guard condition and validate them. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_referenced_actions` | Method | Extract action names referenced in a guard condition. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_against_schemas` | Method | Validate field references against action output schemas. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_with_schemas` | Method | Perform both dependency and schema validation. | - |
| `schema_field_validator.py` | Module | Schema-aware field validation for UDF output schemas. | - |
| `SchemaFieldValidationResult` | Class | Result of validating a field path against a JSON Schema. | - |
| `SchemaFieldValidator` | Class | Validates field paths against JSON Schema definitions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_multiple_paths` | Method | Validate multiple field paths at once. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_field_path` | Method | Validate that a field path exists in the JSON Schema. | - |

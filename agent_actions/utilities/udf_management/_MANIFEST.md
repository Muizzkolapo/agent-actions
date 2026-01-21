# Udf Management Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [type_conversion](type_conversion/_MANIFEST.md) | Type conversion utilities for UDF type hints. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `tooling.py` | Module | Module for loading and running user-defined functions from a specified module. | `configuration`, `errors`, `utilities` |
| `load_user_defined_function` | Function | Load a user-defined function from a specified module. | - |
| `execute_user_defined_function` | Function | Execute UDF with input and output schema validation. | - |
| `udf_registry.py` | Module | UDF (User-Defined Function) Registry for Agent Actions. | `configuration`, `errors`, `utilities` |
| `FileUDFResult` | Class | Result type for FILE-level UDFs with explicit source mapping. | - |
| `udf_tool` | Function | Decorator to register a UDF with type-based schema. | - |
| `get_udf` | Function | Retrieve a registered UDF by name (case-insensitive). | - |
| `get_udf_metadata` | Function | Get complete UDF metadata including schema and granularity. | - |
| `list_udfs` | Function | List all registered UDFs with their metadata. | - |
| `clear_registry` | Function | Clear the UDF registry. Thread-safe. | - |

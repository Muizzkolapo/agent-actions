# UDF Management Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `registry.py` | Module | Thread-safe UDF registry decorator plus helpers for retrieving metadata and clearing the cache. | `errors`, `logging` |
| `FileUDFResult` | Dataclass | Optional FILE-granularity return wrapper. Tools can return plain lists instead — the framework handles all metadata. | — |
| `udf_tool` | Function | Decorator that registers UDFs with optional schema typing/validation control. | `config`, `logging` |
| `get_udf` | Function | Case-insensitive lookup for registered UDF functions (raises `FunctionNotFoundError`). | `errors` |
| `get_udf_metadata` | Function | Returns stored metadata (schema, granularity, module info) for a UDF. | `errors` |
| `list_udfs` | Function | Enumerates registered UDFs with schema summaries for CLI exposure. | `logging` |
| `clear_registry` | Function | Clears the registry (test cleanup) in a thread-safe manner. | `logging` |
| `tooling.py` | Module | Utilities for loading/executing user-defined functions with schema validation support. | `errors`, `logging` |
| `load_user_defined_function` | Function | Dynamically imports a module and returns the requested callable, searching sys.path if needed. | `errors` |
| `execute_user_defined_function` | Function | Runs a UDF (optionally validates output against compiled schemas) and surfaces validation errors. | `errors` |

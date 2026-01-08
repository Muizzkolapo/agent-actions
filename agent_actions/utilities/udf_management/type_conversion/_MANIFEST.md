# Type Conversion Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `converters.py` | Module | Type converters for Python type hints to unified schema format. | `errors` |
| `is_typeddict` | Function | Check if a type is a TypedDict. | - |
| `derive_schema_from_type` | Function | Derive unified schema from Python type hint. | - |
| `unified_to_json_schema` | Function | Convert unified schema format to standard JSON Schema. | - |
| `clear_schema_cache` | Function | Clear the type schema cache. Useful for testing. | - |

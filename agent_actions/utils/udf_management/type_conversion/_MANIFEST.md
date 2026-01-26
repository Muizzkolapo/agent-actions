# UDF Type Conversion Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `converters.py` | Module | Converts TypedDict, dataclass, and (optional) Pydantic models into the unified schema format, caches results, and exposes helpers for JSON Schema output. | `logging`, `errors` |
| `derive_schema_from_type` | Function | Derives a cached unified schema dict from a Python type hint, firing cache events, and enforcing supported types. | `logging`, `errors` |
| `unified_to_json_schema` | Function | Converts the unified schema format to a strict JSON Schema dict for jsonschema validation. | `jsonschema`, `errors` |
| `is_typeddict` | Function | Safe TypedDict detector compatible with Python 3.9 and optional Pydantic/dataclass types. | `typing` |
| `clear_schema_cache` | Function | Clears the derived schema cache and emits invalidation telemetry (testing utility). | `logging` |
| `HAS_PYDANTIC` | Constant | Indicates whether Pydantic is available to support BaseModel conversion. | `logging` |

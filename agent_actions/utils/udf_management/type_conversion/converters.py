"""Type conversion utilities for UDF management.

This module previously contained converters from Python type hints
(TypedDict, Pydantic, dataclass) to the unified schema format.

Output schemas are now defined exclusively via YAML ``schema:`` in workflow
configs.  The type-hint-based machinery (derive_schema_from_type,
unified_to_json_schema, etc.) has been removed.
"""

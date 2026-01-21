"""Type conversion utilities for UDF type hints.

Provides conversion from Python type hints (TypedDict, Pydantic, dataclass)
to the unified schema format used by @udf_tool decorator.
"""

from .converters import (
    derive_schema_from_type,
    unified_to_json_schema,
    is_typeddict,
    clear_schema_cache,
    HAS_PYDANTIC,
)

__all__ = [
    "derive_schema_from_type",
    "unified_to_json_schema",
    "is_typeddict",
    "clear_schema_cache",
    "HAS_PYDANTIC",
]

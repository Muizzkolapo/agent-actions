"""Type conversion utilities for UDF type hints.

Provides conversion from Python type hints (TypedDict, Pydantic, dataclass)
to the unified schema format used by @udf_tool decorator.

Example:
    from typing import TypedDict
    from agent_actions.utilities.udf_management.type_conversion import derive_schema_from_type

    class UserInput(TypedDict):
        name: str
        age: int

    schema = derive_schema_from_type(UserInput)
    # {'name': 'UserInput', 'fields': [{'id': 'name', 'type': 'string', 'required': True}, ...]}
"""

from .converters import derive_schema_from_type, unified_to_json_schema
from .detector import detect_type_category, is_typeddict, TypeCategory, HAS_PYDANTIC

__all__ = [
    'derive_schema_from_type',
    'unified_to_json_schema',
    'detect_type_category',
    'is_typeddict',
    'TypeCategory',
    'HAS_PYDANTIC',
]

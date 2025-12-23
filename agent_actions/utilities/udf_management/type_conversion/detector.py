"""Type detection utilities for Python type hints.

Provides unambiguous detection of TypedDict, Pydantic BaseModel, and dataclass types.
Detection order matters since all three have __annotations__.
"""

import dataclasses
import sys
from enum import Enum
from typing import Type

# Optional Pydantic support
try:
    from pydantic import BaseModel as PydanticBaseModel
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    PydanticBaseModel = None  # type: ignore


class TypeCategory(Enum):
    """Categories of supported type hints for schema derivation."""

    PYDANTIC = "pydantic"
    DATACLASS = "dataclass"
    TYPEDDICT = "typeddict"
    UNSUPPORTED = "unsupported"


def is_typeddict(tp: Type) -> bool:
    """
    Check if a type is a TypedDict.

    Python 3.10+ has typing.is_typeddict, but we need 3.9 compatibility.
    Must exclude Pydantic and dataclass since they also have __annotations__.

    Args:
        tp: Type to check

    Returns:
        True if tp is a TypedDict
    """
    if sys.version_info >= (3, 10):
        from typing import is_typeddict as stdlib_is_typeddict
        return stdlib_is_typeddict(tp)

    # Python 3.9 fallback - must explicitly exclude other types
    if HAS_PYDANTIC and isinstance(tp, type) and issubclass(tp, PydanticBaseModel):
        return False
    if dataclasses.is_dataclass(tp):
        return False

    return (
        hasattr(tp, '__annotations__') and
        hasattr(tp, '__total__') and
        hasattr(tp, '__required_keys__')
    )


def detect_type_category(type_hint: Type) -> TypeCategory:
    """
    Detect the category of a type hint.

    Detection order (most specific to least):
    1. Pydantic BaseModel (has model_json_schema method - unique to Pydantic v2)
    2. dataclass (is_dataclass check - stdlib function)
    3. TypedDict (has __required_keys__ and __total__ - must be last)

    This order prevents false positives since all three have __annotations__.

    Args:
        type_hint: The type to categorize

    Returns:
        TypeCategory indicating the type's category
    """
    # Pydantic v2 check - only Pydantic v2 models have model_json_schema
    if HAS_PYDANTIC and hasattr(type_hint, 'model_json_schema'):
        return TypeCategory.PYDANTIC

    # Dataclass check - use stdlib function
    if dataclasses.is_dataclass(type_hint):
        return TypeCategory.DATACLASS

    # TypedDict check - must be last since others have __annotations__
    if is_typeddict(type_hint):
        return TypeCategory.TYPEDDICT

    return TypeCategory.UNSUPPORTED

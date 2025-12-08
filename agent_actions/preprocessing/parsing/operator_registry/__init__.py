"""
Operator registry for WHERE clause processing.

This module provides a registry system for operators used in WHERE clause evaluation.

The module has been refactored into submodules for better maintainability:
- base: Base classes and type definitions
- comparison: Comparison operators (==, !=, <, >, IN, LIKE, BETWEEN, etc.)
- logical: Logical operators (AND, OR, NOT)
- functions: Function operators (LENGTH, UPPER, LOWER, TRIM)
- registry: OperatorRegistry class with auto-discovery
"""

# Base classes and types
from .base import (
    BaseOperator,
    ComparisonOperator,
    LogicalOperator,
    FunctionOperator,
    OperatorInfo,
    OperatorType,
)

# Comparison operators
from .comparison import (
    EqualOperator,
    NotEqualOperator,
    LessThanOperator,
    LessEqualOperator,
    GreaterThanOperator,
    GreaterEqualOperator,
    InOperator,
    NotInOperator,
    ContainsOperator,
    NotContainsOperator,
    LikeOperator,
    NotLikeOperator,
    BetweenOperator,
    NotBetweenOperator,
    IsNullOperator,
    IsNotNullOperator,
)

# Logical operators
from .logical import (
    AndOperator,
    OrOperator,
    NotOperator,
)

# Function operators
from .functions import (
    LengthFunction,
    UpperFunction,
    LowerFunction,
    TrimFunction,
)

# Registry
from .registry import (
    OperatorRegistry,
    get_global_registry,
)

# Define __all__ for explicit public API
__all__ = [
    # Base classes and types
    "BaseOperator",
    "ComparisonOperator",
    "LogicalOperator",
    "FunctionOperator",
    "OperatorInfo",
    "OperatorType",
    # Comparison operators
    "EqualOperator",
    "NotEqualOperator",
    "LessThanOperator",
    "LessEqualOperator",
    "GreaterThanOperator",
    "GreaterEqualOperator",
    "InOperator",
    "NotInOperator",
    "ContainsOperator",
    "NotContainsOperator",
    "LikeOperator",
    "NotLikeOperator",
    "BetweenOperator",
    "NotBetweenOperator",
    "IsNullOperator",
    "IsNotNullOperator",
    # Logical operators
    "AndOperator",
    "OrOperator",
    "NotOperator",
    # Function operators
    "LengthFunction",
    "UpperFunction",
    "LowerFunction",
    "TrimFunction",
    # Registry
    "OperatorRegistry",
    "get_global_registry",
]

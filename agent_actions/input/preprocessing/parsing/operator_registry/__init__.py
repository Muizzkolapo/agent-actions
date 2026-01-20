"""
Operator registry for WHERE clause processing.
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

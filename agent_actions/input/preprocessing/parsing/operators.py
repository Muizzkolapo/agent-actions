"""Comparison, logical, and function operators for WHERE clause evaluation."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class OperatorType(Enum):
    """Types of operators."""

    COMPARISON = "comparison"
    LOGICAL = "logical"
    FUNCTION = "function"


@dataclass
class OperatorInfo:
    """Metadata about an operator (used by parser for grammar construction)."""

    name: str
    symbol: str
    operator_type: OperatorType
    precedence: int
    associativity: str  # "left", "right", "none"
    arity: int  # 1 for unary, 2 for binary
    description: str


def _safe_compare(op):
    """Wrap a relational comparison so TypeError → False."""

    def wrapper(left: Any, right: Any = None) -> bool:
        try:
            result: bool = op(left, right)
            return result
        except TypeError:
            return False

    return wrapper


def _sql_like(left: Any, right: Any = None) -> bool:
    """SQL LIKE pattern matching (case-insensitive)."""
    if left is None or right is None:
        return False
    text = str(left)
    pattern = str(right)
    pattern = pattern.replace("%", "\x00").replace("_", "\x01")
    escaped = re.escape(pattern)
    regex_pattern = escaped.replace("\x00", ".*").replace("\x01", ".")
    try:
        return bool(re.match(f"^{regex_pattern}$", text, re.IGNORECASE))
    except re.error:
        return False


def _validate_range(range_val: Any) -> bool:
    return isinstance(range_val, (list, tuple)) and len(range_val) == 2


OPERATORS: dict[str, Any] = {
    # Equality
    "EQ": lambda left, right=None: left == right,
    "NE": lambda left, right=None: left != right,
    # Relational (TypeError → False)
    "LT": _safe_compare(lambda left, right: left < right),
    "LE": _safe_compare(lambda left, right: left <= right),
    "GT": _safe_compare(lambda left, right: left > right),
    "GE": _safe_compare(lambda left, right: left >= right),
    # Membership
    "IN": lambda left, right=None: left in right
    if isinstance(right, (list, tuple, set))
    else False,
    "NOT_IN": lambda left, right=None: (
        left not in right if isinstance(right, (list, tuple, set)) else False
    ),
    # String
    "CONTAINS": lambda left, right=None: str(right) in str(left) if left is not None else False,
    "NOT_CONTAINS": lambda left, right=None: (
        str(right) not in str(left) if left is not None else False
    ),
    # Pattern
    "LIKE": _sql_like,
    "NOT_LIKE": lambda left, right=None: not _sql_like(left, right),
    # Range
    "BETWEEN": lambda left, right=None: (
        _safe_compare(lambda l, r: r[0] <= l <= r[1])(left, right)
        if _validate_range(right)
        else False
    ),
    "NOT_BETWEEN": lambda left, right=None: (
        not _safe_compare(lambda l, r: r[0] <= l <= r[1])(left, right)
        if _validate_range(right)
        else False
    ),
    # Null (unary — right unused for uniform call signature)
    "IS_NULL": lambda left, right=None: left is None,  # pyright: ignore[reportUnusedVariable]
    "IS_NOT_NULL": lambda left, right=None: left is not None,  # pyright: ignore[reportUnusedVariable]
}


def _length(args: list[Any]) -> int:
    if len(args) != 1:
        raise ValueError("LENGTH function requires exactly 1 argument")
    arg = args[0]
    if arg is None:
        return 0
    if isinstance(arg, (list, tuple, dict, str)):
        return len(arg)
    return len(str(arg))


def _upper(args: list[Any]) -> str:
    if len(args) != 1:
        raise ValueError("UPPER function requires exactly 1 argument")
    return str(args[0]).upper() if args[0] is not None else ""


def _lower(args: list[Any]) -> str:
    if len(args) != 1:
        raise ValueError("LOWER function requires exactly 1 argument")
    return str(args[0]).lower() if args[0] is not None else ""


def _trim(args: list[Any]) -> str:
    if len(args) != 1:
        raise ValueError("TRIM function requires exactly 1 argument")
    return str(args[0]).strip() if args[0] is not None else ""


FUNCTIONS: dict[str, Any] = {
    "LENGTH": _length,
    "UPPER": _upper,
    "LOWER": _lower,
    "TRIM": _trim,
}


OPERATOR_INFO: dict[str, OperatorInfo] = {
    # Comparison
    "EQ": OperatorInfo("EQ", "==", OperatorType.COMPARISON, 7, "left", 2, "Equality comparison"),
    "NE": OperatorInfo("NE", "!=", OperatorType.COMPARISON, 7, "left", 2, "Not equal comparison"),
    "LT": OperatorInfo("LT", "<", OperatorType.COMPARISON, 6, "left", 2, "Less than comparison"),
    "LE": OperatorInfo(
        "LE", "<=", OperatorType.COMPARISON, 6, "left", 2, "Less than or equal comparison"
    ),
    "GT": OperatorInfo("GT", ">", OperatorType.COMPARISON, 6, "left", 2, "Greater than comparison"),
    "GE": OperatorInfo(
        "GE", ">=", OperatorType.COMPARISON, 6, "left", 2, "Greater than or equal comparison"
    ),
    "IN": OperatorInfo("IN", "IN", OperatorType.COMPARISON, 7, "left", 2, "In array/list"),
    "NOT_IN": OperatorInfo(
        "NOT_IN", "NOT IN", OperatorType.COMPARISON, 7, "left", 2, "Not in array/list"
    ),
    "CONTAINS": OperatorInfo(
        "CONTAINS", "CONTAINS", OperatorType.COMPARISON, 7, "left", 2, "String contains"
    ),
    "NOT_CONTAINS": OperatorInfo(
        "NOT_CONTAINS", "NOT CONTAINS", OperatorType.COMPARISON, 7, "left", 2, "String not contains"
    ),
    "LIKE": OperatorInfo(
        "LIKE", "LIKE", OperatorType.COMPARISON, 7, "left", 2, "SQL LIKE pattern matching"
    ),
    "NOT_LIKE": OperatorInfo(
        "NOT_LIKE",
        "NOT LIKE",
        OperatorType.COMPARISON,
        7,
        "left",
        2,
        "SQL NOT LIKE pattern matching",
    ),
    "BETWEEN": OperatorInfo(
        "BETWEEN", "BETWEEN", OperatorType.COMPARISON, 7, "left", 2, "Between range"
    ),
    "NOT_BETWEEN": OperatorInfo(
        "NOT_BETWEEN", "NOT BETWEEN", OperatorType.COMPARISON, 7, "left", 2, "Not between range"
    ),
    "IS_NULL": OperatorInfo(
        "IS_NULL", "IS NULL", OperatorType.COMPARISON, 8, "none", 1, "Is null/None"
    ),
    "IS_NOT_NULL": OperatorInfo(
        "IS_NOT_NULL", "IS NOT NULL", OperatorType.COMPARISON, 8, "none", 1, "Is not null/None"
    ),
    # Logical
    "AND": OperatorInfo("AND", "AND", OperatorType.LOGICAL, 3, "left", 2, "Logical AND"),
    "OR": OperatorInfo("OR", "OR", OperatorType.LOGICAL, 2, "left", 2, "Logical OR"),
    "NOT": OperatorInfo("NOT", "NOT", OperatorType.LOGICAL, 9, "right", 1, "Logical NOT"),
    # Functions
    "LENGTH": OperatorInfo(
        "LENGTH", "LENGTH", OperatorType.FUNCTION, 10, "none", 1, "Get length of value"
    ),
    "UPPER": OperatorInfo(
        "UPPER", "UPPER", OperatorType.FUNCTION, 10, "none", 1, "Convert to uppercase"
    ),
    "LOWER": OperatorInfo(
        "LOWER", "LOWER", OperatorType.FUNCTION, 10, "none", 1, "Convert to lowercase"
    ),
    "TRIM": OperatorInfo("TRIM", "TRIM", OperatorType.FUNCTION, 10, "none", 1, "Trim whitespace"),
}


def list_operators(operator_type: OperatorType | None = None) -> list[OperatorInfo]:
    """List all operators, optionally filtered by type."""
    ops = list(OPERATOR_INFO.values())
    if operator_type is not None:
        ops = [info for info in ops if info.operator_type == operator_type]
    return sorted(ops, key=lambda x: (x.operator_type.value, x.precedence, x.name))


def get_operator_info(name: str) -> OperatorInfo | None:
    """Get operator info by name."""
    return OPERATOR_INFO.get(name)

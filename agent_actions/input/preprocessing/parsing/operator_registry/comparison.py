"""
Comparison operators for the operator registry.

This module contains all built-in comparison operators including
equality, relational, membership, string matching, range, and null checks.
"""

from typing import Any, Dict, Optional
import re

from .base import ComparisonOperator, OperatorInfo, OperatorType


# Equality operators
class EqualOperator(ComparisonOperator):
    """Equality comparison operator (==)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return left == right

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "EQ", "==", OperatorType.COMPARISON, 7, "left", 2, "Equality comparison"
        )


class NotEqualOperator(ComparisonOperator):
    """Not equal comparison operator (!=)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return left != right

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "NE", "!=", OperatorType.COMPARISON, 7, "left", 2, "Not equal comparison"
        )


# Relational operators
class LessThanOperator(ComparisonOperator):
    """Less than comparison operator (<)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        try:
            return left < right
        except TypeError:
            return False

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "LT", "<", OperatorType.COMPARISON, 6, "left", 2, "Less than comparison"
        )


class LessEqualOperator(ComparisonOperator):
    """Less than or equal comparison operator (<=)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        try:
            return left <= right
        except TypeError:
            return False

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "LE", "<=", OperatorType.COMPARISON, 6, "left", 2, "Less than or equal comparison"
        )


class GreaterThanOperator(ComparisonOperator):
    """Greater than comparison operator (>)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        try:
            return left > right
        except TypeError:
            return False

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "GT", ">", OperatorType.COMPARISON, 6, "left", 2, "Greater than comparison"
        )


class GreaterEqualOperator(ComparisonOperator):
    """Greater than or equal comparison operator (>=)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        try:
            return left >= right
        except TypeError:
            return False

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "GE", ">=", OperatorType.COMPARISON, 6, "left", 2, "Greater than or equal comparison"
        )


# Membership operators
class InOperator(ComparisonOperator):
    """In array/list operator (IN)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        if not isinstance(right, (list, tuple, set)):
            return False
        return left in right

    def get_info(self) -> OperatorInfo:
        return OperatorInfo("IN", "IN", OperatorType.COMPARISON, 7, "left", 2, "In array/list")


class NotInOperator(ComparisonOperator):
    """Not in array/list operator (NOT IN)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        if not isinstance(right, (list, tuple, set)):
            return True
        return left not in right

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "NOT_IN", "NOT IN", OperatorType.COMPARISON, 7, "left", 2, "Not in array/list"
        )


# String operators
class ContainsOperator(ComparisonOperator):
    """String contains operator (CONTAINS)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        if left is None:
            return False
        return str(right) in str(left)

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "CONTAINS", "CONTAINS", OperatorType.COMPARISON, 7, "left", 2, "String contains"
        )


class NotContainsOperator(ComparisonOperator):
    """String not contains operator (NOT CONTAINS)."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        if left is None:
            return True
        return str(right) not in str(left)

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "NOT_CONTAINS",
            "NOT CONTAINS",
            OperatorType.COMPARISON,
            7,
            "left",
            2,
            "String not contains",
        )


class LikeOperator(ComparisonOperator):
    """SQL LIKE pattern matching operator."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        if left is None or right is None:
            return False

        text = str(left)
        pattern = str(right)

        # Convert SQL LIKE pattern to regex
        regex_pattern = self._convert_sql_pattern_to_regex(pattern)

        try:
            return bool(re.match(regex_pattern, text, re.IGNORECASE))
        except re.error:
            return False

    def _convert_sql_pattern_to_regex(self, pattern: str) -> str:
        """
        Convert SQL LIKE pattern to Python regex.

        Args:
            pattern: SQL LIKE pattern with % and _ wildcards

        Returns:
            Equivalent regex pattern
        """
        # Replace % and _ with placeholders first
        pattern = pattern.replace("%", "\x00").replace("_", "\x01")

        # Escape special regex characters
        escaped = re.escape(pattern)

        # Replace placeholders with regex equivalents
        regex_pattern = escaped.replace("\x00", ".*").replace("\x01", ".")

        # Add anchors to match the entire string
        return f"^{regex_pattern}$"

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "LIKE", "LIKE", OperatorType.COMPARISON, 7, "left", 2, "SQL LIKE pattern matching"
        )


class NotLikeOperator(ComparisonOperator):
    """SQL NOT LIKE pattern matching operator."""

    _like_op = LikeOperator()  # Shared instance; LikeOperator must remain stateless

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return not self._like_op.evaluate(left, right, context)

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "NOT_LIKE",
            "NOT LIKE",
            OperatorType.COMPARISON,
            7,
            "left",
            2,
            "SQL NOT LIKE pattern matching",
        )


# Range operators
class BetweenOperator(ComparisonOperator):
    """BETWEEN range operator."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        if not self._validate_range(right):
            return False
        try:
            return right[0] <= left <= right[1]
        except TypeError:
            return False

    def _validate_range(self, range_val: Any) -> bool:
        """
        Validate range is a 2-element sequence.

        Args:
            range_val: The range value to validate

        Returns:
            True if valid range, False otherwise
        """
        return isinstance(range_val, (list, tuple)) and len(range_val) == 2

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "BETWEEN", "BETWEEN", OperatorType.COMPARISON, 7, "left", 2, "Between range"
        )


class NotBetweenOperator(ComparisonOperator):
    """NOT BETWEEN range operator."""

    _between_op = BetweenOperator()  # Shared instance; BetweenOperator must remain stateless

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return not self._between_op.evaluate(left, right, context)

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "NOT_BETWEEN", "NOT BETWEEN", OperatorType.COMPARISON, 7, "left", 2, "Not between range"
        )


# Null operators
class IsNullOperator(ComparisonOperator):
    """IS NULL operator."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return left is None

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "IS_NULL", "IS NULL", OperatorType.COMPARISON, 8, "none", 1, "Is null/None"
        )


class IsNotNullOperator(ComparisonOperator):
    """IS NOT NULL operator."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return left is not None

    def get_info(self) -> OperatorInfo:
        return OperatorInfo(
            "IS_NOT_NULL", "IS NOT NULL", OperatorType.COMPARISON, 8, "none", 1, "Is not null/None"
        )

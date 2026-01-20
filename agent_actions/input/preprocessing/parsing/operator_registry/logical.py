"""
Logical operators for the operator registry.

This module contains all built-in logical operators including
AND, OR, and NOT for boolean operations.
"""

from typing import Any, Dict, Optional

from .base import LogicalOperator, OperatorInfo, OperatorType


class AndOperator(LogicalOperator):
    """Logical AND operator."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return bool(left) and bool(right)

    def get_info(self) -> OperatorInfo:
        return OperatorInfo("AND", "AND", OperatorType.LOGICAL, 3, "left", 2, "Logical AND")


class OrOperator(LogicalOperator):
    """Logical OR operator."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return bool(left) or bool(right)

    def get_info(self) -> OperatorInfo:
        return OperatorInfo("OR", "OR", OperatorType.LOGICAL, 2, "left", 2, "Logical OR")


class NotOperator(LogicalOperator):
    """Logical NOT operator."""

    def evaluate(
        self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return not bool(left)

    def get_info(self) -> OperatorInfo:
        return OperatorInfo("NOT", "NOT", OperatorType.LOGICAL, 9, "right", 1, "Logical NOT")

"""
Base classes and types for the operator registry system.

This module defines the foundational abstractions for all operators,
including base operator classes, type enumerations, and metadata structures.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class OperatorType(Enum):
    """Types of operators in the registry."""
    COMPARISON = "comparison"
    LOGICAL = "logical"
    FUNCTION = "function"


@dataclass
class OperatorInfo:
    """Information about a registered operator."""
    name: str
    symbol: str
    operator_type: OperatorType
    precedence: int
    associativity: str  # "left", "right", "none"
    arity: int  # Number of operands (1 for unary, 2 for binary)
    description: str


class BaseOperator(ABC):
    """Base class for all operators."""

    @abstractmethod
    def evaluate(
        self,
        left: Any,
        right: Any = None,
        context: Optional[Dict[str,
        Any]] = None) -> Any:

        """
        Evaluate the operator with given operands.

        Args:
            left: Left operand
            right: Right operand (None for unary operators)
            context: Optional evaluation context

        Returns:
            Result of the operation
        """

    @abstractmethod
    def get_info(self) -> OperatorInfo:
        """Get operator information."""


class ComparisonOperator(BaseOperator):
    """Base class for comparison operators."""

    def evaluate(
        self,
        left: Any,
        right: Any = None,
        context: Optional[Dict[str,
        Any]] = None) -> bool:

        """
        Evaluate the comparison operator with given operands.

        Args:
            left: Left operand
            right: Right operand (None for unary operators)
            context: Optional evaluation context

        Returns:
            Boolean result of the comparison
        """
        raise NotImplementedError("Subclasses must implement evaluate()")


class LogicalOperator(BaseOperator):
    """Base class for logical operators."""

    def evaluate(
        self,
        left: Any,
        right: Any = None,
        context: Optional[Dict[str,
        Any]] = None) -> bool:

        """
        Evaluate the logical operator with given operands.

        Args:
            left: Left operand
            right: Right operand (None for unary operators like NOT)
            context: Optional evaluation context

        Returns:
            Boolean result of the logical operation
        """
        raise NotImplementedError("Subclasses must implement evaluate()")


class FunctionOperator(BaseOperator):
    """Base class for function operators."""

    @abstractmethod
    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> Any:
        """
        Evaluate the function with given arguments.

        Args:
            args: List of function arguments
            context: Optional evaluation context

        Returns:
            Result of the function
        """

    def evaluate(
        self,
        left: Any,
        right: Any = None,
        context: Optional[Dict[str,
        Any]] = None) -> Any:

        """Wrapper for function evaluation."""
        args = [left] if right is None else [left, right]
        return self.evaluate_function(args, context)

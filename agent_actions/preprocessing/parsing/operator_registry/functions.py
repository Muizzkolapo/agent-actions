"""
Function operators for the operator registry.

This module contains all built-in function operators including
string manipulation and value inspection functions.
"""

from typing import Any, Dict, List, Optional

from .base import FunctionOperator, OperatorInfo, OperatorType


class LengthFunction(FunctionOperator):
    """LENGTH function."""

    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> int:
        if len(args) != 1:
            raise ValueError("LENGTH function requires exactly 1 argument")

        arg = args[0]
        if arg is None:
            return 0
        elif isinstance(arg, (list, tuple, dict, str)):
            return len(arg)
        else:
            return len(str(arg))

    def get_info(self) -> OperatorInfo:
        return OperatorInfo("LENGTH", "LENGTH", OperatorType.FUNCTION, 10, "none", 1, "Get length of value")


class UpperFunction(FunctionOperator):
    """UPPER function."""

    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> str:
        if len(args) != 1:
            raise ValueError("UPPER function requires exactly 1 argument")

        arg = args[0]
        return str(arg).upper() if arg is not None else ""

    def get_info(self) -> OperatorInfo:
        return OperatorInfo("UPPER", "UPPER", OperatorType.FUNCTION, 10, "none", 1, "Convert to uppercase")


class LowerFunction(FunctionOperator):
    """LOWER function."""

    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> str:
        if len(args) != 1:
            raise ValueError("LOWER function requires exactly 1 argument")

        arg = args[0]
        return str(arg).lower() if arg is not None else ""

    def get_info(self) -> OperatorInfo:
        return OperatorInfo("LOWER", "LOWER", OperatorType.FUNCTION, 10, "none", 1, "Convert to lowercase")


class TrimFunction(FunctionOperator):
    """TRIM function."""

    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> str:
        if len(args) != 1:
            raise ValueError("TRIM function requires exactly 1 argument")

        arg = args[0]
        return str(arg).strip() if arg is not None else ""

    def get_info(self) -> OperatorInfo:
        return OperatorInfo("TRIM", "TRIM", OperatorType.FUNCTION, 10, "none", 1, "Trim whitespace")

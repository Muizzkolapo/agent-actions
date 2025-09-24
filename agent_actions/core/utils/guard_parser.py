"""Guard expression parser for handling both UDF and SQL-like conditions."""

import re
from typing import Tuple, Literal, Optional
from enum import Enum


class GuardType(str, Enum):
    """Types of guard expressions."""
    SQL = "sql"
    UDF = "udf"


class GuardExpression:
    """Parsed guard expression."""

    def __init__(self, guard_type: GuardType, expression: str, original: str):
        self.type = guard_type
        self.expression = expression
        self.original = original

    def __repr__(self):
        return f"GuardExpression(type={self.type}, expression='{self.expression}')"


class GuardParser:
    """Parser for guard expressions supporting both SQL-like and UDF syntax."""

    UDF_PREFIX = "udf:"

    @classmethod
    def parse(cls, guard: str) -> GuardExpression:
        """
        Parse a guard expression and determine its type.

        Args:
            guard: Guard expression string

        Returns:
            GuardExpression with parsed type and expression

        Examples:
            parse('questionable != "Low Value"') -> GuardExpression(SQL, 'questionable != "Low Value"')
            parse('udf:module.function') -> GuardExpression(UDF, 'module.function')
        """
        if not guard or not isinstance(guard, str):
            raise ValueError("Guard expression must be a non-empty string")

        original_guard = guard
        guard = guard.strip()

        if guard.startswith(cls.UDF_PREFIX):
            # UDF expression
            udf_expression = guard[len(cls.UDF_PREFIX):].strip()
            if not udf_expression:
                raise ValueError("UDF guard expression cannot be empty after 'udf:' prefix")

            # Validate UDF expression format (module.function pattern)
            cls._validate_udf_expression(udf_expression)

            return GuardExpression(
                guard_type=GuardType.UDF,
                expression=udf_expression,
                original=original_guard
            )
        else:
            # SQL-like expression
            cls._validate_sql_expression(guard)

            return GuardExpression(
                guard_type=GuardType.SQL,
                expression=guard,
                original=original_guard
            )

    @classmethod
    def _validate_udf_expression(cls, expression: str) -> None:
        """
        Validate UDF expression format.

        Args:
            expression: UDF expression (e.g., 'module.function')

        Raises:
            ValueError: If expression format is invalid
        """
        # Basic pattern: module.function or module.submodule.function
        pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+$'

        if not re.match(pattern, expression):
            raise ValueError(
                f"Invalid UDF expression format: '{expression}'. "
                "Expected format: 'module.function' or 'module.submodule.function'"
            )

        # Security checks - prevent dangerous patterns
        dangerous_patterns = [
            '__import__', 'exec', 'eval', 'compile', 'open', 'file',
            'input', 'raw_input', 'reload', 'vars', 'globals', 'locals',
            'dir', 'hasattr', 'getattr', 'setattr', 'delattr', '__'
        ]

        expression_lower = expression.lower()
        for pattern in dangerous_patterns:
            if pattern in expression_lower:
                raise ValueError(
                    f"UDF expression contains potentially dangerous pattern: {pattern}"
                )

    @classmethod
    def _validate_sql_expression(cls, expression: str) -> None:
        """
        Validate SQL-like expression for basic safety.

        Args:
            expression: SQL-like expression

        Raises:
            ValueError: If expression contains dangerous patterns
        """
        # Basic safety checks for SQL expressions
        dangerous_patterns = [
            '__import__', 'exec', 'eval', 'compile', 'open', 'file',
            'input', 'raw_input', 'reload', 'vars', 'globals', 'locals',
            'dir', 'hasattr', 'getattr', 'setattr', 'delattr'
        ]

        expression_lower = expression.lower()
        for pattern in dangerous_patterns:
            if pattern in expression_lower:
                raise ValueError(
                    f"SQL expression contains potentially dangerous pattern: {pattern}"
                )

    @classmethod
    def is_udf_guard(cls, guard: str) -> bool:
        """Check if a guard expression is a UDF."""
        return guard and guard.strip().startswith(cls.UDF_PREFIX)

    @classmethod
    def is_sql_guard(cls, guard: str) -> bool:
        """Check if a guard expression is SQL-like."""
        return guard and not guard.strip().startswith(cls.UDF_PREFIX)


    @classmethod
    def parse_consolidated(cls, guard_data) -> 'GuardConfig':
        """
        Parse consolidated guard configuration.

        Args:
            guard_data: String (legacy) or dict (new format)

        Returns:
            GuardConfig instance
        """
        from .consolidated_guard import parse_guard_config
        return parse_guard_config(guard_data)


def parse_guard(guard: str) -> GuardExpression:
    """Convenience function to parse guard expressions."""
    return GuardParser.parse(guard)


__all__ = ["GuardType", "GuardExpression", "GuardParser", "parse_guard"]
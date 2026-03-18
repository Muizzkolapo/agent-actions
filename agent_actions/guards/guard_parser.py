"""Guard expression parser for handling both UDF and SQL-like conditions."""

import re
from enum import Enum

from agent_actions.errors import ValidationError
from agent_actions.utils.constants import (
    DANGEROUS_PATTERNS,
    DANGEROUS_PATTERNS_UDF,
    contains_dangerous_pattern,
)


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
    def parse(cls, guard: str | None) -> GuardExpression:
        """Parse a guard expression string into a typed GuardExpression (SQL or UDF).

        Note: SQL guard expressions operate on column values only. Built-in
        Python names such as ``file``, ``input``, ``vars``, and ``dir`` are
        treated as column references, not as Python builtins, so they will not
        trigger the dangerous-pattern validator.
        """
        if not guard or not isinstance(guard, str):
            raise ValidationError(
                "Guard expression must be a non-empty string",
                context={
                    "guard": guard,
                    "guard_type": str(type(guard)),
                    "operation": "parse_guard",
                    "failed_field": "guard",
                    "expected": 'Non-empty string (e.g., "udf:module.function" or SQL expression)',
                    "actual_value": guard,
                    "suggestion": (
                        "Provide a valid guard expression as a non-empty string. "
                        'Use "udf:module.function" for UDF guards or SQL-like expressions '
                        "for SQL guards."
                    ),
                },
            )
        original_guard = guard
        guard = guard.strip()
        if not guard:
            raise ValidationError(
                "Guard expression must not be empty or whitespace-only",
                context={
                    "guard": original_guard,
                    "operation": "parse_guard",
                    "failed_field": "guard_expression",
                },
            )
        if guard.startswith(cls.UDF_PREFIX):
            udf_expression = guard[len(cls.UDF_PREFIX) :].strip()
            if not udf_expression:
                raise ValidationError(
                    "UDF guard expression cannot be empty after 'udf:' prefix",
                    context={
                        "guard": original_guard,
                        "operation": "parse_udf_guard",
                        "failed_field": "udf_expression",
                        "expected": (
                            'Non-empty UDF expression after "udf:" prefix '
                            '(e.g., "udf:module.function")'
                        ),
                        "actual_value": udf_expression,
                        "suggestion": (
                            "Provide a valid UDF expression in the format "
                            '"udf:module.function" or "udf:module.submodule.function".'
                        ),
                    },
                )
            cls._validate_udf_expression(udf_expression)
            return GuardExpression(
                guard_type=GuardType.UDF, expression=udf_expression, original=original_guard
            )
        cls._validate_sql_expression(guard)
        return GuardExpression(guard_type=GuardType.SQL, expression=guard, original=original_guard)

    @classmethod
    def _validate_udf_expression(cls, expression: str) -> None:
        """Validate UDF expression format (e.g., 'module.function').

        Raises:
            ValidationError: If expression format is invalid or contains dangerous patterns
        """
        pattern = "^[a-zA-Z_][a-zA-Z0-9_]*(?:\\.[a-zA-Z_][a-zA-Z0-9_]*)+$"
        if not re.match(pattern, expression):
            raise ValidationError(
                f"Invalid UDF expression format: '{expression}'. "
                "Expected format: 'module.function' or 'module.submodule.function'",
                context={
                    "expression": expression,
                    "expected_pattern": pattern,
                    "operation": "validate_udf_expression",
                    "failed_field": "udf_expression",
                    "expected": (
                        "Valid Python module path "
                        '(e.g., "module.function" or "module.submodule.function")'
                    ),
                    "actual_value": expression,
                    "suggestion": (
                        "Ensure the UDF expression follows Python module naming conventions: "
                        "starts with letter/underscore, contains only alphanumeric characters "
                        "and underscores, separated by dots."
                    ),
                },
            )
        expression_lower = expression.lower()
        matched = contains_dangerous_pattern(expression_lower, DANGEROUS_PATTERNS_UDF)
        if matched:
            raise ValidationError(
                f"UDF expression contains potentially dangerous pattern: {matched}",
                context={
                    "expression": expression,
                    "dangerous_pattern": matched,
                    "operation": "validate_udf_expression",
                    "failed_field": "udf_expression",
                    "expected": (
                        "UDF expression without dangerous patterns "
                        "like exec, eval, __import__, etc."
                    ),
                    "actual_value": expression,
                    "suggestion": (
                        f'Remove the dangerous pattern "{matched}" from your UDF expression. '
                        "Use safe function calls only."
                    ),
                },
            )

    @classmethod
    def _validate_sql_expression(cls, expression: str) -> None:
        """Validate that a SQL-like expression does not contain dangerous patterns.

        Raises:
            ValidationError: If expression contains dangerous patterns
        """
        expression_lower = expression.lower()
        matched = contains_dangerous_pattern(expression_lower, DANGEROUS_PATTERNS)
        if matched:
            raise ValidationError(
                f"SQL expression contains potentially dangerous pattern: {matched}",
                context={
                    "expression": expression,
                    "dangerous_pattern": matched,
                    "operation": "validate_sql_expression",
                    "failed_field": "sql_expression",
                    "expected": (
                        "SQL expression without dangerous patterns "
                        "like exec, eval, __import__, etc."
                    ),
                    "actual_value": expression,
                    "suggestion": (
                        f'Remove the dangerous pattern "{matched}" '
                        "from your SQL guard expression. "
                        "Use safe SQL operators and column references only."
                    ),
                },
            )


def parse_guard(guard: str | None) -> GuardExpression:
    """Convenience function to parse guard expressions."""
    return GuardParser.parse(guard)


__all__ = ["GuardType", "GuardExpression", "GuardParser", "parse_guard"]

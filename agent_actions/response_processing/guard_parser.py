"""Guard expression parser for handling both UDF and SQL-like conditions."""
import re
from enum import Enum

class GuardType(str, Enum):
    """Types of guard expressions."""
    SQL = 'sql'
    UDF = 'udf'

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
    UDF_PREFIX = 'udf:'

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
            from agent_actions.shared.exceptions import ValidationError
            raise ValidationError(
                'Guard expression must be a non-empty string',
                context={
                    'guard': guard,
                    'guard_type': str(type(guard)),
                    'operation': 'parse_guard',
                    'failed_field': 'guard',
                    'expected': 'Non-empty string (e.g., "udf:module.function" or SQL expression)',
                    'actual_value': guard,
                    'suggestion': 'Provide a valid guard expression as a non-empty string. Use "udf:module.function" for UDF guards or SQL-like expressions for SQL guards.'
                }
            )
        original_guard = guard
        guard = guard.strip()
        if guard.startswith(cls.UDF_PREFIX):
            udf_expression = guard[len(cls.UDF_PREFIX):].strip()
            if not udf_expression:
                from agent_actions.shared.exceptions import ValidationError
                raise ValidationError(
                    "UDF guard expression cannot be empty after 'udf:' prefix",
                    context={
                        'guard': original_guard,
                        'operation': 'parse_udf_guard',
                        'failed_field': 'udf_expression',
                        'expected': 'Non-empty UDF expression after "udf:" prefix (e.g., "udf:module.function")',
                        'actual_value': udf_expression,
                        'suggestion': 'Provide a valid UDF expression in the format "udf:module.function" or "udf:module.submodule.function".'
                    }
                )
            cls._validate_udf_expression(udf_expression)
            return GuardExpression(guard_type=GuardType.UDF, expression=udf_expression, original=original_guard)
        else:
            cls._validate_sql_expression(guard)
            return GuardExpression(guard_type=GuardType.SQL, expression=guard, original=original_guard)

    @classmethod
    def _validate_udf_expression(cls, expression: str) -> None:
        """
        Validate UDF expression format.

        Args:
            expression: UDF expression (e.g., 'module.function')

        Raises:
            ValueError: If expression format is invalid
        """
        pattern = '^[a-zA-Z_][a-zA-Z0-9_]*(?:\\.[a-zA-Z_][a-zA-Z0-9_]*)+$'
        if not re.match(pattern, expression):
            from agent_actions.shared.exceptions import ValidationError
            raise ValidationError(
                f"Invalid UDF expression format: '{expression}'. Expected format: 'module.function' or 'module.submodule.function'",
                context={
                    'expression': expression,
                    'expected_pattern': pattern,
                    'operation': 'validate_udf_expression',
                    'failed_field': 'udf_expression',
                    'expected': 'Valid Python module path (e.g., "module.function" or "module.submodule.function")',
                    'actual_value': expression,
                    'suggestion': 'Ensure the UDF expression follows Python module naming conventions: starts with letter/underscore, contains only alphanumeric characters and underscores, separated by dots.'
                }
            )
        dangerous_patterns = ['__import__', 'exec', 'eval', 'compile', 'open', 'file', 'input', 'raw_input', 'reload', 'vars', 'globals', 'locals', 'dir', 'hasattr', 'getattr', 'setattr', 'delattr', '__']
        expression_lower = expression.lower()
        for pattern in dangerous_patterns:
            if pattern in expression_lower:
                from agent_actions.shared.exceptions import ValidationError
                raise ValidationError(
                    f'UDF expression contains potentially dangerous pattern: {pattern}',
                    context={
                        'expression': expression,
                        'dangerous_pattern': pattern,
                        'operation': 'validate_udf_expression',
                        'failed_field': 'udf_expression',
                        'expected': 'UDF expression without dangerous patterns like exec, eval, __import__, etc.',
                        'actual_value': expression,
                        'suggestion': f'Remove the dangerous pattern "{pattern}" from your UDF expression. Use safe function calls only.'
                    }
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
        dangerous_patterns = ['__import__', 'exec', 'eval', 'compile', 'open', 'file', 'input', 'raw_input', 'reload', 'vars', 'globals', 'locals', 'dir', 'hasattr', 'getattr', 'setattr', 'delattr']
        expression_lower = expression.lower()
        for pattern in dangerous_patterns:
            if pattern in expression_lower:
                from agent_actions.shared.exceptions import ValidationError
                raise ValidationError(
                    f'SQL expression contains potentially dangerous pattern: {pattern}',
                    context={
                        'expression': expression,
                        'dangerous_pattern': pattern,
                        'operation': 'validate_sql_expression',
                        'failed_field': 'sql_expression',
                        'expected': 'SQL expression without dangerous patterns like exec, eval, __import__, etc.',
                        'actual_value': expression,
                        'suggestion': f'Remove the dangerous pattern "{pattern}" from your SQL guard expression. Use safe SQL operators and column references only.'
                    }
                )

    @classmethod
    def is_udf_guard(cls, guard: str) -> bool:
        """Check if a guard expression is a UDF."""
        return guard and guard.strip().startswith(cls.UDF_PREFIX)

    @classmethod
    def is_sql_guard(cls, guard: str) -> bool:
        """Check if a guard expression is SQL-like."""
        return guard and (not guard.strip().startswith(cls.UDF_PREFIX))

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
__all__ = ['GuardType', 'GuardExpression', 'GuardParser', 'parse_guard']
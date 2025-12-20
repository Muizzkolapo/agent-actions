"""
SQL-like WHERE clause parser for data filtering and condition evaluation.

This module provides utilities for parsing and evaluating SQL-like WHERE clauses,
enabling flexible data filtering with support for various operators, nested fields,
and pattern matching.
"""
import ast
import re
import json
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WhereCondition:
    """Represents a single WHERE clause condition with field, operator, and value."""
    field: str
    operator: str
    value: Any


class WhereClauseParser:
    """Parse SQL-like WHERE clauses for data filtering"""

    OPERATORS = {
        "!=": lambda a, b: a != b,
        "==": lambda a, b: a == b,
        "=": lambda a, b: a == b,
        ">=": lambda a, b: WhereClauseParser._safe_compare(a, b, lambda x, y: x >= y),
        "<=": lambda a, b: WhereClauseParser._safe_compare(a, b, lambda x, y: x <= y),
        ">": lambda a, b: WhereClauseParser._safe_compare(a, b, lambda x, y: x > y),
        "<": lambda a, b: WhereClauseParser._safe_compare(a, b, lambda x, y: x < y),
        "IN": lambda a, b: a in b if isinstance(b, (list, tuple)) else False,
        "NOT IN": lambda a, b: a not in b if isinstance(b, (list, tuple)) else True,
        "LIKE": lambda a, b: WhereClauseParser._like_match(a, b),  # pylint: disable=unnecessary-lambda
        "CONTAINS": lambda a, b: str(b) in str(a) if a is not None else False,
        "NOT CONTAINS": lambda a, b: str(b) not in str(a) if a is not None else True,
        "IS NULL": lambda a, b: a is None,
        "IS NOT NULL": lambda a, b: a is not None,
    }

    @classmethod
    def parse(cls, where_clause: str) -> List[WhereCondition]:
        """Parse WHERE clause into conditions"""
        if where_clause is None:
            raise TypeError("where_clause cannot be None")
        where_clause = where_clause.strip()
        if not where_clause:
            return []
        conditions: List[WhereCondition] = []

        parts = re.split(r"\s+AND\s+", where_clause, flags=re.IGNORECASE)
        for part in parts:
            condition = cls._parse_condition(part.strip())
            if condition:
                conditions.append(condition)
        return conditions

    @classmethod
    def _parse_condition(cls, condition_str: str) -> Optional[WhereCondition]:
        """Parse a single condition"""
        # Check for malformed triple operators
        if "===" in condition_str or "!==" in condition_str:
            return None

        upper = condition_str.upper()
        if "IS NULL" in upper:
            field = upper.replace("IS NULL", "").strip()
            field_original = condition_str.replace("IS NULL", "").strip()
            return WhereCondition(field=field_original, operator="IS NULL", value=None)
        if "IS NOT NULL" in upper:
            field_original = condition_str.replace("IS NOT NULL", "").strip()
            return WhereCondition(field=field_original, operator="IS NOT NULL", value=None)

        for op in sorted(cls.OPERATORS.keys(), key=len, reverse=True):
            pattern = re.compile(rf"\s*{re.escape(op)}\s*", flags=re.IGNORECASE)
            if pattern.search(condition_str):
                parts = pattern.split(condition_str)
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    field = parts[0].strip()
                    value_str = parts[1].strip()
                    value = cls._parse_value(value_str)
                    return WhereCondition(field=field, operator=op, value=value)
        return None

    @classmethod
    def _parse_value(cls, value_str: str) -> Any:  # pylint: disable=too-many-return-statements
        """Parse value string into appropriate Python type"""
        value_str = value_str.strip()
        if (value_str.startswith("\"") and value_str.endswith("\"")) or (
            value_str.startswith("'") and value_str.endswith("'")
        ):
            return value_str[1:-1]
        if value_str.lower() == "true":
            return True
        if value_str.lower() == "false":
            return False
        if value_str.lower() == "null":
            return None
        try:
            return int(value_str)
        except ValueError:
            try:
                return float(value_str)
            except ValueError:
                pass
        if value_str.startswith("[") and value_str.endswith("]"):
            try:
                return json.loads(value_str)
            except json.JSONDecodeError:
                # Try Python literal evaluation for single-quoted arrays
                try:
                    return ast.literal_eval(value_str)
                except (ValueError, SyntaxError):
                    pass
        return value_str

    @classmethod
    def _like_match(cls, value: Any, pattern: str) -> bool:
        """Implement LIKE pattern matching with % wildcards."""
        if value is None:
            return False

        # Convert pattern to regex
        # Escape regex special chars except %
        escaped = re.escape(str(pattern))
        # Convert % back to .*
        regex_pattern = escaped.replace(r'\%', '.*')

        try:
            return bool(re.match(f'^{regex_pattern}$', str(value)))
        except re.error:
            return False

    @classmethod
    def evaluate(cls, data: Dict[str, Any], conditions: List[WhereCondition]) -> bool:
        """Evaluate conditions against data"""
        for condition in conditions:
            field_value = cls._get_nested_value(data, condition.field)
            operator_func = cls.OPERATORS[condition.operator]
            if not operator_func(field_value, condition.value):
                return False
        return True

    @classmethod
    def _get_nested_value(cls, data: Dict[str, Any], field_path: str) -> Any:
        """Get value from nested dictionary using dot notation"""
        if not field_path:
            return data
        keys = field_path.split(".")
        value: Any = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value

    @classmethod
    def _safe_compare(cls, a: Any, b: Any, compare_func) -> bool:
        """Safely compare two values with type checking."""
        if a is None or b is None:
            return False
        try:
            return compare_func(a, b)
        except TypeError:
            # Handle type mismatches gracefully
            return False


# Simple filter service for compatibility with existing code
class SimpleWhereFilter:
    """A simple WHERE clause filter service for data filtering and guard evaluation."""

    def __init__(self):
        self.parser = WhereClauseParser()

    def filter_item(self, data: Dict[str, Any], where_clause: str) -> bool:
        """
        Evaluate if a data item matches a WHERE clause condition.

        Args:
            data: Data to evaluate against the condition
            where_clause: WHERE clause string (e.g., "status == 'active'")

        Returns:
            True if item matches the condition, False otherwise.
            Defaults to True (include item) on parsing errors.
        """
        try:
            conditions = self.parser.parse(where_clause)
            if not conditions:  # No valid conditions parsed
                return True  # Default to including item on parse failure
            return self.parser.evaluate(data, conditions)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug(
                "Where clause evaluation failed, defaulting to including item: %s",
                e,
                extra={
                    'where_clause': where_clause,
                    'operation': 'where_clause_evaluation'
                }
            )
            return True  # Default to including item on error

    def evaluate_safe_skip_condition(
        self, condition_config: Dict[str, Any], context: Dict[str, Any]
    ) -> bool:
        """
        Safely evaluate a skip condition for legacy compatibility.

        Args:
            condition_config: Skip condition configuration
            context: Evaluation context

        Returns:
            True if the condition indicates the agent should be skipped
        """
        try:
            # Handle simple where clause evaluation
            if 'where' in condition_config:
                where_clause = condition_config['where']
                conditions = self.parser.parse(where_clause)
                return not self.parser.evaluate(context, conditions)
            return False
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug(
                "Skip condition evaluation failed, defaulting to not skipping: %s",
                e,
                extra={
                    'condition_config': condition_config,
                    'operation': 'skip_condition_evaluation'
                }
            )
            # Default to not skipping on error
            return False


# Global filter instance for backward compatibility
_global_filter = None  # pylint: disable=invalid-name


def get_global_filter() -> SimpleWhereFilter:
    """Get the global WHERE clause filter instance."""
    global _global_filter  # pylint: disable=global-statement
    if _global_filter is None:
        _global_filter = SimpleWhereFilter()
    return _global_filter


def evaluate_safe_skip_condition(condition_config: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """
    Safely evaluate a skip condition.

    Args:
        condition_config: Skip condition configuration
        context: Evaluation context

    Returns:
        True if the condition indicates the agent should be skipped
    """
    filter_service = get_global_filter()
    return filter_service.evaluate_safe_skip_condition(condition_config, context)


def evaluate_safe_expression(expression: str, context: Dict[str, Any]) -> bool:
    """
    Safely evaluate an expression.

    Args:
        expression: Expression to evaluate
        context: Evaluation context

    Returns:
        Result of expression evaluation
    """
    try:
        parser = WhereClauseParser()
        conditions = parser.parse(expression)
        if not conditions:  # No valid conditions parsed means invalid syntax
            return False
        return parser.evaluate(context, conditions)
    except Exception:  # pylint: disable=broad-exception-caught
        return False

"""
Built-in constraint validators for reprompting system.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


# Type map for field_types constraint
TYPE_MAP: Dict[str, type] = {
    "string": str,
    "str": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": (int, float),  # type: ignore
    "array": list,
    "list": list,
    "object": dict,
    "dict": dict,
    "bool": bool,
    "boolean": bool,
}


@dataclass
class ConstraintResult:
    """Result of constraint validation.

    Attributes:
        passed: Whether all constraints passed
        error: Error message if validation failed
        constraint_name: Name of the failed constraint (if any)
    """

    passed: bool
    error: Optional[str] = None
    constraint_name: Optional[str] = None


# Type for constraint functions: (response, value) -> (passed, error_msg)
ConstraintFunc = Callable[[Any, Any], Tuple[bool, str]]


def _check_not_contains(response: Any, value: Union[str, List[str]]) -> Tuple[bool, str]:
    """Check that response does not contain specified string(s)."""
    response_str = str(response).lower()
    if isinstance(value, str):
        values = [value]
    else:
        values = value

    for v in values:
        if v.lower() in response_str:
            return False, f"Response must not contain: '{v}'"
    return True, ""


def _check_contains(response: Any, value: Union[str, List[str]]) -> Tuple[bool, str]:
    """Check that response contains specified string(s)."""
    response_str = str(response).lower()
    if isinstance(value, str):
        values = [value]
    else:
        values = value

    missing = [v for v in values if v.lower() not in response_str]
    if missing:
        return False, f"Response must contain: {missing}"
    return True, ""


def _check_max_length(response: Any, max_len: int) -> Tuple[bool, str]:
    """Check that response does not exceed max length."""
    response_str = str(response)
    if len(response_str) > max_len:
        return False, f"Response exceeds max length {max_len} (got {len(response_str)})"
    return True, ""


def _check_min_length(response: Any, min_len: int) -> Tuple[bool, str]:
    """Check that response meets minimum length."""
    response_str = str(response)
    if len(response_str) < min_len:
        return False, f"Response below min length {min_len} (got {len(response_str)})"
    return True, ""


def _check_required_fields(response: Any, fields: Union[str, List[str]]) -> Tuple[bool, str]:
    """Check that response (dict) contains all required fields."""
    if not isinstance(response, dict):
        return False, "Response must be a dictionary to check required_fields"

    if isinstance(fields, str):
        fields = [fields]

    missing = [f for f in fields if f not in response]
    if missing:
        return False, f"Missing required fields: {missing}"
    return True, ""


def _check_non_empty(response: Any, fields: Union[str, List[str]]) -> Tuple[bool, str]:
    """Check that specified fields are not empty (not None, '', [], {})."""
    if not isinstance(response, dict):
        return False, "Response must be a dictionary to check non_empty"

    if isinstance(fields, str):
        fields = [fields]

    empty_values = [None, "", [], {}]
    empty_fields = [f for f in fields if response.get(f) in empty_values]
    if empty_fields:
        return False, f"Fields must not be empty: {empty_fields}"
    return True, ""


def _check_field_types(response: Any, type_map: Dict[str, str]) -> Tuple[bool, str]:
    """Check that fields have expected types.

    Args:
        response: Response dict
        type_map: Dict mapping field names to expected types
                  e.g., {"name": "string", "count": "int", "items": "array"}
    """
    if not isinstance(response, dict):
        return False, "Response must be a dictionary to check field_types"

    mismatches = []
    for field_name, expected_type in type_map.items():
        if field_name not in response:
            continue  # Skip missing fields (use required_fields for that)

        value = response[field_name]
        if expected_type not in TYPE_MAP:
            mismatches.append(f"Unknown type '{expected_type}' for field '{field_name}'")
            continue

        expected_class = TYPE_MAP[expected_type]
        if not isinstance(value, expected_class):
            actual_type = type(value).__name__
            mismatches.append(f"Field '{field_name}' expected {expected_type}, got {actual_type}")

    if mismatches:
        return False, f"Type mismatches: {'; '.join(mismatches)}"
    return True, ""


def _check_regex_match(response: Any, pattern: str) -> Tuple[bool, str]:
    """Check that response matches regex pattern."""
    response_str = str(response)
    if not re.search(pattern, response_str):
        return False, f"Response must match pattern: {pattern}"
    return True, ""


def _check_regex_not_match(response: Any, pattern: str) -> Tuple[bool, str]:
    """Check that response does not match regex pattern."""
    response_str = str(response)
    if re.search(pattern, response_str):
        return False, f"Response must not match pattern: {pattern}"
    return True, ""


# Registry of built-in constraint functions
BUILTIN_CONSTRAINTS: Dict[str, ConstraintFunc] = {
    "not_contains": _check_not_contains,
    "contains": _check_contains,
    "max_length": _check_max_length,
    "min_length": _check_min_length,
    "required_fields": _check_required_fields,
    "non_empty": _check_non_empty,
    "field_types": _check_field_types,
    "regex_match": _check_regex_match,
    "regex_not_match": _check_regex_not_match,
}


class ConstraintValidator:
    """Validates responses against a list of constraints.

    Supports built-in constraints and custom validator functions.

    Usage:
        validator = ConstraintValidator()
        result = validator.validate(response, [
            {"not_contains": "maze"},
            {"required_fields": ["name", "description"]},
        ])
        if not result.passed:
            print(f"Failed: {result.error}")
    """

    def __init__(self) -> None:
        """Initialize with built-in constraints."""
        self.constraints = BUILTIN_CONSTRAINTS.copy()

    def register(self, name: str, func: ConstraintFunc) -> None:
        """Register a custom constraint function.

        Args:
            name: Constraint name (used in YAML config)
            func: Function taking (response, value) and returning (passed, error_msg)
        """
        self.constraints[name] = func

    def validate(self, response: Any, constraint_configs: List[Dict[str, Any]]) -> ConstraintResult:
        """Validate response against all constraints.

        Runs constraints in order and returns on first failure.

        Args:
            response: The LLM response to validate
            constraint_configs: List of constraint configurations
                Each config is a dict with constraint name as key

        Returns:
            ConstraintResult with passed=True if all constraints pass,
            or passed=False with error details on first failure
        """
        for config in constraint_configs:
            for constraint_name, constraint_value in config.items():
                # Skip if not a registered constraint
                if constraint_name not in self.constraints:
                    # Could be a custom validator reference - skip for now
                    continue

                constraint_func = self.constraints[constraint_name]
                passed, error_msg = constraint_func(response, constraint_value)

                if not passed:
                    return ConstraintResult(
                        passed=False,
                        error=error_msg,
                        constraint_name=constraint_name,
                    )

        return ConstraintResult(passed=True)

    def get_constraint_names(self) -> List[str]:
        """Get list of registered constraint names."""
        return list(self.constraints.keys())

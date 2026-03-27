"""
Utility for validating schema type strings.
"""

import ast
import json
from typing import Any


class SchemaTypeValidator:
    """
    Validates schema type strings for agent configurations.

    Supports:
    - Basic types: string, number, integer, boolean, array, object
    - Array types: array[string], array[number], etc.
    - Complex types: array[object:{'prop': 'type', ...}]

    This is extracted from the original _is_valid_schema_type method
    to isolate the complexity (CC 13).
    """

    def __repr__(self) -> str:
        """Return string representation of validator."""
        return f"{self.__class__.__name__}()"

    def is_valid(self) -> bool:
        """
        Check if validator is properly configured.

        Returns:
            bool: Always True for SchemaTypeValidator (stateless)
        """
        return True

    def is_valid_schema_type(
        self, type_str: str, valid_types: set[str], valid_array_types: set[str]
    ) -> bool:
        """
        Check if a schema type string is valid.

        Args:
            type_str: The type string to validate
            valid_types: Set of valid basic types
            valid_array_types: Set of valid array types

        Returns:
            bool: True if the type is valid, False otherwise

        Examples:
            >>> validator = SchemaTypeValidator()
            >>> validator.is_valid_schema_type('string', {'string'}, set())
            True
            >>> validator.is_valid_schema_type('array[object:{"name": "string"}]',
            ...                                 {'string'}, set())
            True
        """
        # Check if it's a basic or array type
        if type_str in valid_types or type_str in valid_array_types:
            return True

        # Check if it's a complex array[object:...] type
        if type_str.startswith("array[object:") and type_str.endswith("]"):
            return self._validate_complex_object_type(type_str)

        return False

    def _validate_complex_object_type(self, type_str: str) -> bool:
        """
        Validate complex object type like array[object:{'prop': 'type'}].

        Args:
            type_str: Type string starting with 'array[object:' and ending with ']'

        Returns:
            bool: True if valid, False otherwise
        """
        # Extract properties part between 'array[object:' and ']'
        properties_part = type_str[13:-1]

        # Try to parse as dictionary
        properties_dict = self._parse_properties_string(properties_part)

        if properties_dict is None:
            return False

        # Validate it's a dictionary
        if not isinstance(properties_dict, dict):
            return False  # type: ignore[unreachable]

        # Validate each property
        return self._validate_object_properties(properties_dict)

    def _parse_properties_string(self, properties_str: str) -> dict[str, Any] | None:
        """
        Parse properties string as JSON or Python literal.

        Tries JSON first (more strict), then falls back to Python literal eval.

        Args:
            properties_str: String representation of properties dict

        Returns:
            Parsed dictionary or None if parsing failed
        """
        # Try JSON parsing first
        try:
            return json.loads(properties_str)  # type: ignore[no-any-return]
        except (ValueError, json.JSONDecodeError) as e:
            # Fall through to try Python literal eval
            _ = e  # Suppress unused variable warning

        # Fallback to Python literal eval
        try:
            return ast.literal_eval(properties_str)  # type: ignore[no-any-return]
        except (ValueError, SyntaxError):
            return None

    def _validate_object_properties(self, properties: dict[str, Any]) -> bool:
        """
        Validate that object properties have correct structure.

        Each property must:
        - Have string key (property name)
        - Have string value (property type)
        - Type must be one of: string, number, integer, boolean, object

        Args:
            properties: Dictionary of property definitions

        Returns:
            bool: True if all properties valid, False otherwise
        """
        valid_prop_types = {"string", "number", "integer", "boolean", "object"}

        for prop_name, prop_type in properties.items():
            # Check property name is string
            if not isinstance(prop_name, str):
                return False  # type: ignore[unreachable]

            # Check property type is string
            if not isinstance(prop_type, str):
                return False

            # Clean backslashes and strip required marker
            cleaned_type = prop_type.replace("\\", "")
            base_prop_type = cleaned_type.rstrip("!")

            # Check type is valid
            if base_prop_type not in valid_prop_types:
                return False

        return True

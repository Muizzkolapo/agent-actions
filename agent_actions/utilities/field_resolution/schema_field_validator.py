"""Schema-aware field validation for UDF output schemas.

Validates that field references (e.g., 'my_udf.result.count') exist in the
UDF's output schema definition. Enables compile-time validation of field
references against JSON Schema structures.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SchemaFieldValidationResult:
    """Result of validating a field path against a JSON Schema."""

    field_path: List[str]  # Field path components (e.g., ['result', 'count'])
    action_name: str       # Name of action being validated
    exists: bool           # Whether field path exists in schema
    field_type: Optional[str] = None  # JSON Schema type if found
    error: Optional[str] = None       # Error message if validation failed
    is_required: bool = False         # Whether field is in 'required' list


class SchemaFieldValidator:
    """Validates field paths against JSON Schema definitions.

    Handles:
    - Nested objects: response.data.count
    - Optional fields (not in 'required' list)
    - Type extraction for future type checking
    - Array items (basic support)

    Example:
        validator = SchemaFieldValidator()

        schema = {
            'type': 'object',
            'properties': {
                'result': {'type': 'string'},
                'data': {
                    'type': 'object',
                    'properties': {
                        'count': {'type': 'integer'}
                    }
                }
            },
            'required': ['result']
        }

        result = validator.validate_field_path(
            field_path=['data', 'count'],
            json_schema=schema,
            action_name='my_udf'
        )

        assert result.exists
        assert result.field_type == 'integer'
    """

    def validate_field_path(
        self,
        field_path: List[str],
        json_schema: Dict[str, Any],
        action_name: str
    ) -> SchemaFieldValidationResult:
        """
        Validate that a field path exists in the JSON Schema.

        Args:
            field_path: Path components (e.g., ['response', 'data', 'count'])
            json_schema: JSON Schema to validate against
            action_name: Name of action for error messages

        Returns:
            SchemaFieldValidationResult with validation details

        Example:
            result = validator.validate_field_path(
                field_path=['result'],
                json_schema={'type': 'object', 'properties': {'result': {'type': 'string'}}},
                action_name='my_action'
            )
        """
        if not field_path:
            return SchemaFieldValidationResult(
                field_path=field_path,
                action_name=action_name,
                exists=False,
                error="Empty field path"
            )

        # Traverse schema following field path
        exists, field_type = self._traverse_schema_path(json_schema, field_path)

        if not exists:
            # Build helpful error message
            available_fields = self._extract_available_fields(json_schema)
            available_msg = f". Available fields: {', '.join(available_fields)}" if available_fields else ""

            error = (
                f"Field '{'.'.join(field_path)}' not found in '{action_name}' output schema"
                f"{available_msg}"
            )

            return SchemaFieldValidationResult(
                field_path=field_path,
                action_name=action_name,
                exists=False,
                error=error
            )

        # Check if field is required
        is_required = self._is_field_required(json_schema, field_path)

        return SchemaFieldValidationResult(
            field_path=field_path,
            action_name=action_name,
            exists=True,
            field_type=field_type,
            is_required=is_required
        )

    def _traverse_schema_path(
        self,
        schema: Dict[str, Any],
        path: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Traverse nested JSON Schema following field path.

        Args:
            schema: Current schema node
            path: Remaining path components to traverse

        Returns:
            Tuple of (exists, json_type)
            - exists: True if path found
            - json_type: JSON Schema type if found (e.g., 'string', 'integer', 'object')

        Example:
            schema = {
                'type': 'object',
                'properties': {
                    'data': {
                        'type': 'object',
                        'properties': {
                            'count': {'type': 'integer'}
                        }
                    }
                }
            }

            exists, type_str = _traverse_schema_path(schema, ['data', 'count'])
            # Returns: (True, 'integer')
        """
        if not path:
            # Reached end of path - return type of current schema node
            return (True, schema.get('type'))

        # Get current field name
        field_name = path[0]
        remaining_path = path[1:]

        # Check if current schema is an object with properties
        if schema.get('type') == 'object':
            properties = schema.get('properties', {})

            # Field not in properties
            if field_name not in properties:
                return (False, None)

            field_schema = properties[field_name]

            # If no more path, we found the field
            if not remaining_path:
                return (True, field_schema.get('type'))

            # Continue traversing for nested fields
            return self._traverse_schema_path(field_schema, remaining_path)

        # Handle array types - traverse into items schema
        elif schema.get('type') == 'array':
            items_schema = schema.get('items')
            if not items_schema:
                return (False, None)

            # Traverse the items schema with the full remaining path
            # This allows accessing properties of array item objects
            return self._traverse_schema_path(items_schema, path)

        else:
            # Not an object or array - can't traverse further
            return (False, None)

    def _extract_available_fields(self, schema: Dict[str, Any]) -> List[str]:
        """
        Extract list of available field names from schema.

        Args:
            schema: JSON Schema object

        Returns:
            List of field names at the top level

        Example:
            schema = {
                'type': 'object',
                'properties': {
                    'result': {'type': 'string'},
                    'count': {'type': 'integer'}
                }
            }

            fields = _extract_available_fields(schema)
            # Returns: ['result', 'count']
        """
        if schema.get('type') != 'object':
            return []

        properties = schema.get('properties', {})
        return sorted(properties.keys())

    def _is_field_required(
        self,
        schema: Dict[str, Any],
        field_path: List[str]
    ) -> bool:
        """
        Check if a field is in the 'required' list.

        Args:
            schema: JSON Schema object
            field_path: Path to check (only checks first component)

        Returns:
            True if field is required

        Example:
            schema = {
                'type': 'object',
                'properties': {
                    'result': {'type': 'string'},
                    'optional': {'type': 'string'}
                },
                'required': ['result']
            }

            is_required = _is_field_required(schema, ['result'])
            # Returns: True
        """
        if not field_path:
            return False

        required_fields = schema.get('required', [])
        return field_path[0] in required_fields

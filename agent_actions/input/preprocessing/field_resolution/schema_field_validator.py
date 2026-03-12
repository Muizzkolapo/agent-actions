"""Schema-aware field validation for UDF output schemas."""

from dataclasses import dataclass
from typing import Any


@dataclass
class SchemaFieldValidationResult:
    """Result of validating a field path against a JSON Schema."""

    field_path: list[str]  # Field path components (e.g., ['result', 'count'])
    action_name: str  # Name of action being validated
    exists: bool  # Whether field path exists in schema
    field_type: str | None = None  # JSON Schema type if found
    error: str | None = None  # Error message if validation failed
    is_required: bool = False  # Whether field is in 'required' list

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"SchemaFieldValidationResult(field_path={self.field_path}, "
            f"action_name={self.action_name}, exists={self.exists})"
        )


class SchemaFieldValidator:
    """Validates field paths against JSON Schema definitions."""

    def validate_multiple_paths(
        self, field_paths: list[list[str]], json_schema: dict[str, Any], action_name: str
    ) -> list[SchemaFieldValidationResult]:
        """Validate multiple field paths at once."""
        return [self.validate_field_path(path, json_schema, action_name) for path in field_paths]

    def validate_field_path(
        self, field_path: list[str], json_schema: dict[str, Any], action_name: str
    ) -> SchemaFieldValidationResult:
        """Validate that a field path exists in the JSON Schema."""
        if not field_path:
            return SchemaFieldValidationResult(
                field_path=field_path,
                action_name=action_name,
                exists=False,
                error="Empty field path",
            )

        exists, field_type = self._traverse_schema_path(json_schema, field_path)

        if not exists:
            available_fields = self._extract_available_fields(json_schema)
            available_msg = (
                f". Available fields: {', '.join(available_fields)}" if available_fields else ""
            )

            error = (
                f"Field '{'.'.join(field_path)}' not found in "
                f"'{action_name}' output schema{available_msg}"
            )

            return SchemaFieldValidationResult(
                field_path=field_path, action_name=action_name, exists=False, error=error
            )

        is_required = self._is_field_required(json_schema, field_path)

        return SchemaFieldValidationResult(
            field_path=field_path,
            action_name=action_name,
            exists=True,
            field_type=field_type,
            is_required=is_required,
        )

    def _traverse_schema_path(
        self, schema: dict[str, Any], path: list[str]
    ) -> tuple[bool, str | None]:
        """Traverse nested JSON Schema following field path. Returns (exists, json_type)."""
        if not path:
            return (True, schema.get("type"))

        field_name = path[0]
        remaining_path = path[1:]

        if schema.get("type") == "object":
            return self._traverse_object_schema(schema, field_name, remaining_path)

        if schema.get("type") == "array":
            return self._traverse_array_schema(schema, path)

        return (False, None)

    def _traverse_object_schema(
        self, schema: dict[str, Any], field_name: str, remaining_path: list[str]
    ) -> tuple[bool, str | None]:
        """Traverse object schema properties."""
        properties = schema.get("properties", {})

        if field_name not in properties:
            return (False, None)

        field_schema = properties[field_name]

        if not remaining_path:
            return (True, field_schema.get("type"))

        return self._traverse_schema_path(field_schema, remaining_path)

    def _traverse_array_schema(
        self, schema: dict[str, Any], path: list[str]
    ) -> tuple[bool, str | None]:
        """Traverse array schema items."""
        items_schema = schema.get("items")
        if not items_schema:
            return (False, None)

        return self._traverse_schema_path(items_schema, path)

    def _extract_available_fields(self, schema: dict[str, Any]) -> list[str]:
        """Extract list of available field names from schema."""
        if schema.get("type") != "object":
            return []

        properties = schema.get("properties", {})
        return sorted(properties.keys())

    def _is_field_required(self, schema: dict[str, Any], field_path: list[str]) -> bool:
        """Check if a field is in the 'required' list."""
        if not field_path:
            return False

        required_fields = schema.get("required", [])
        return field_path[0] in required_fields

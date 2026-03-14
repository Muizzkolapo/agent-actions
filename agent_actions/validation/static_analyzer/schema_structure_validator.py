"""Schema structure validation for pre-flight checking."""

import logging
from typing import Any

from .errors import FieldLocation, StaticTypeError

logger = logging.getLogger(__name__)


class SchemaStructureValidator:
    """Validates schema structures for correctness and completeness."""

    # Valid JSON Schema types
    VALID_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}

    def validate_schema(
        self,
        schema: dict[str, Any],
        action_name: str,
        config_field: str = "schema",
    ) -> list[StaticTypeError]:
        """Validate a schema definition for structural correctness."""
        errors: list[StaticTypeError] = []

        if not schema:
            return errors

        if not isinstance(schema, dict):
            errors.append(  # type: ignore[unreachable]
                StaticTypeError(
                    message=f"Schema must be a dictionary, got {type(schema).__name__}",
                    location=FieldLocation(agent_name=action_name, config_field=config_field),
                    referenced_agent=action_name,
                    referenced_field="schema",
                    hint="Schema should be a dict with 'fields' or JSON Schema format",
                )
            )
            return errors

        if "fields" in schema:
            errors.extend(self._validate_unified_format(schema, action_name, config_field))
        elif "type" in schema:
            errors.extend(self._validate_json_schema_format(schema, action_name, config_field))
        elif "properties" in schema:
            errors.extend(
                self._validate_object_properties(
                    schema.get("properties", {}),
                    action_name,
                    config_field,
                    schema.get("required", []),
                )
            )
        else:
            errors.extend(self._validate_inline_shorthand(schema, action_name, config_field))

        return errors

    def _validate_unified_format(
        self,
        schema: dict[str, Any],
        action_name: str,
        config_field: str,
    ) -> list[StaticTypeError]:
        """Validate unified schema format with 'fields' array."""
        errors: list[StaticTypeError] = []

        fields = schema.get("fields", [])
        if not isinstance(fields, list):
            errors.append(
                StaticTypeError(
                    message="Schema 'fields' must be a list",
                    location=FieldLocation(agent_name=action_name, config_field=config_field),
                    referenced_agent=action_name,
                    referenced_field="fields",
                    hint="Example: fields: [{id: 'name', type: 'string'}, ...]",
                )
            )
            return errors

        if len(fields) == 0:
            errors.append(
                StaticTypeError(
                    message="Schema has empty 'fields' list - no fields defined",
                    location=FieldLocation(agent_name=action_name, config_field=config_field),
                    referenced_agent=action_name,
                    referenced_field="fields",
                    hint="Add at least one field definition to the schema",
                )
            )
            return errors

        field_ids: set[str] = set()
        for i, field in enumerate(fields):
            field_errors = self._validate_unified_field(
                field, action_name, config_field, i, field_ids
            )
            errors.extend(field_errors)

        return errors

    def _validate_unified_field(
        self,
        field: Any,
        action_name: str,
        config_field: str,
        index: int,
        seen_ids: set[str],
    ) -> list[StaticTypeError]:
        """Validate a single field in unified format."""
        errors: list[StaticTypeError] = []

        if not isinstance(field, dict):
            errors.append(
                StaticTypeError(
                    message=f"Field at index {index} must be a dictionary",
                    location=FieldLocation(
                        agent_name=action_name,
                        config_field=f"{config_field}.fields[{index}]",
                    ),
                    referenced_agent=action_name,
                    referenced_field=f"fields[{index}]",
                    hint="Each field should be: {id: 'name', type: 'string', ...}",
                )
            )
            return errors

        field_id = field.get("id") or field.get("name")
        if not field_id:
            errors.append(
                StaticTypeError(
                    message=f"Field at index {index} missing 'id' or 'name'",
                    location=FieldLocation(
                        agent_name=action_name,
                        config_field=f"{config_field}.fields[{index}]",
                    ),
                    referenced_agent=action_name,
                    referenced_field=f"fields[{index}]",
                    hint="Add 'id' key to identify the field: {id: 'field_name', type: '...'}",
                )
            )
        elif field_id in seen_ids:
            errors.append(
                StaticTypeError(
                    message=f"Duplicate field id '{field_id}' at index {index}",
                    location=FieldLocation(
                        agent_name=action_name,
                        config_field=f"{config_field}.fields[{index}]",
                    ),
                    referenced_agent=action_name,
                    referenced_field=field_id,
                    hint="Each field must have a unique id",
                )
            )
        else:
            seen_ids.add(field_id)

        field_type = field.get("type")
        if not field_type:
            errors.append(
                StaticTypeError(
                    message=f"Field '{field_id or index}' missing 'type'",
                    location=FieldLocation(
                        agent_name=action_name,
                        config_field=f"{config_field}.fields[{index}]",
                    ),
                    referenced_agent=action_name,
                    referenced_field=str(field_id or f"fields[{index}]"),
                    hint="Add 'type' key: string, number, integer, boolean, array, or object",
                )
            )
        elif field_type not in self.VALID_TYPES:
            if not (field_type.startswith("array[") and field_type.endswith("]")):
                errors.append(
                    StaticTypeError(
                        message=f"Field '{field_id}' has invalid type '{field_type}'",
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field=f"{config_field}.fields[{index}]",
                        ),
                        referenced_agent=action_name,
                        referenced_field=str(field_id),
                        available_fields=self.VALID_TYPES,
                        hint="Use a valid JSON Schema type",
                    )
                )

        if field_type == "array":
            items = field.get("items")
            if not items:
                errors.append(
                    StaticTypeError(
                        message=f"Array field '{field_id}' missing 'items' definition",
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field=f"{config_field}.fields[{index}]",
                        ),
                        referenced_agent=action_name,
                        referenced_field=str(field_id),
                        hint="Add 'items': {type: 'string'} or {type: 'object', properties: {...}}",
                    )
                )
            elif isinstance(items, dict):
                items_type = items.get("type")
                if items_type == "object" and not items.get("properties"):
                    errors.append(
                        StaticTypeError(
                            message=f"Array field '{field_id}' has object items without properties",
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field=f"{config_field}.fields[{index}].items",
                            ),
                            referenced_agent=action_name,
                            referenced_field=str(field_id),
                            hint="Add 'properties' to define object structure: items: {type: object, properties: {...}}",
                        )
                    )

        return errors

    def _validate_json_schema_format(
        self,
        schema: dict[str, Any],
        action_name: str,
        config_field: str,
    ) -> list[StaticTypeError]:
        """Validate JSON Schema format."""
        errors: list[StaticTypeError] = []

        schema_type = schema.get("type")
        if schema_type not in self.VALID_TYPES:
            errors.append(
                StaticTypeError(
                    message=f"Invalid schema type '{schema_type}'",
                    location=FieldLocation(agent_name=action_name, config_field=config_field),
                    referenced_agent=action_name,
                    referenced_field="type",
                    available_fields=self.VALID_TYPES,
                    hint="Use a valid JSON Schema type",
                )
            )
            return errors

        if schema_type == "array":
            items = schema.get("items")
            if not items or not isinstance(items, dict):
                errors.append(
                    StaticTypeError(
                        message="Array schema missing or invalid 'items' definition",
                        location=FieldLocation(agent_name=action_name, config_field=config_field),
                        referenced_agent=action_name,
                        referenced_field="items",
                        hint="Add 'items': {type: 'object', properties: {...}} or {type: 'string'}",
                    )
                )
            elif items.get("type") == "object":
                properties = items.get("properties", {})
                if not properties:
                    errors.append(
                        StaticTypeError(
                            message="Array items have object type but empty 'properties'",
                            location=FieldLocation(
                                agent_name=action_name, config_field=f"{config_field}.items"
                            ),
                            referenced_agent=action_name,
                            referenced_field="properties",
                            hint="Define properties for the object: properties: {name: {type: string}, ...}",
                        )
                    )
                else:
                    errors.extend(
                        self._validate_object_properties(
                            properties,
                            action_name,
                            f"{config_field}.items",
                            items.get("required", []),
                        )
                    )

        elif schema_type == "object":
            properties = schema.get("properties", {})
            if not properties:
                errors.append(
                    StaticTypeError(
                        message="Object schema has empty 'properties'",
                        location=FieldLocation(agent_name=action_name, config_field=config_field),
                        referenced_agent=action_name,
                        referenced_field="properties",
                        hint="Define properties: properties: {name: {type: string}, ...}",
                    )
                )
            else:
                errors.extend(
                    self._validate_object_properties(
                        properties,
                        action_name,
                        config_field,
                        schema.get("required", []),
                    )
                )

        return errors

    def _validate_object_properties(
        self,
        properties: dict[str, Any],
        action_name: str,
        config_field: str,
        required: list[str],
    ) -> list[StaticTypeError]:
        """Validate object properties definition."""
        errors: list[StaticTypeError] = []

        if not isinstance(properties, dict):
            errors.append(  # type: ignore[unreachable]
                StaticTypeError(
                    message="'properties' must be a dictionary",
                    location=FieldLocation(
                        agent_name=action_name, config_field=f"{config_field}.properties"
                    ),
                    referenced_agent=action_name,
                    referenced_field="properties",
                    hint="Example: properties: {name: {type: string}, age: {type: integer}}",
                )
            )
            return errors

        for prop_name, prop_def in properties.items():
            if not isinstance(prop_def, dict):
                errors.append(
                    StaticTypeError(
                        message=f"Property '{prop_name}' definition must be a dictionary",
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field=f"{config_field}.properties.{prop_name}",
                        ),
                        referenced_agent=action_name,
                        referenced_field=prop_name,
                        hint=f"Example: {prop_name}: {{type: string}}",
                    )
                )
                continue

            prop_type = prop_def.get("type")
            if not prop_type:
                errors.append(
                    StaticTypeError(
                        message=f"Property '{prop_name}' missing 'type'",
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field=f"{config_field}.properties.{prop_name}",
                        ),
                        referenced_agent=action_name,
                        referenced_field=prop_name,
                        hint="Add type: string, number, integer, boolean, array, or object",
                    )
                )
            elif prop_type not in self.VALID_TYPES:
                errors.append(
                    StaticTypeError(
                        message=f"Property '{prop_name}' has invalid type '{prop_type}'",
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field=f"{config_field}.properties.{prop_name}",
                        ),
                        referenced_agent=action_name,
                        referenced_field=prop_name,
                        available_fields=self.VALID_TYPES,
                        hint="Use a valid JSON Schema type",
                    )
                )

        if required:
            for req_field in required:
                if req_field not in properties:
                    errors.append(
                        StaticTypeError(
                            message=f"Required field '{req_field}' not defined in properties",
                            location=FieldLocation(
                                agent_name=action_name, config_field=f"{config_field}.required"
                            ),
                            referenced_agent=action_name,
                            referenced_field=req_field,
                            available_fields=set(properties.keys()),
                            hint=f"Add '{req_field}' to properties or remove from required list",
                        )
                    )

        return errors

    def _validate_inline_shorthand(
        self,
        schema: dict[str, Any],
        action_name: str,
        config_field: str,
    ) -> list[StaticTypeError]:
        """Validate inline shorthand format {field_name: 'type'}."""
        errors: list[StaticTypeError] = []

        if not schema:
            return errors

        for field_name, field_type in schema.items():
            if not isinstance(field_type, str):
                errors.append(
                    StaticTypeError(
                        message=f"Inline schema field '{field_name}' type must be a string",
                        location=FieldLocation(
                            agent_name=action_name, config_field=f"{config_field}.{field_name}"
                        ),
                        referenced_agent=action_name,
                        referenced_field=field_name,
                        hint="Example: {name: 'string!', age: 'number'}",
                    )
                )
                continue

            base_type = field_type.rstrip("!")

            if base_type.startswith("array[") and base_type.endswith("]"):
                inner_type = base_type[6:-1]
                if inner_type.startswith("object:"):
                    continue
                elif inner_type not in self.VALID_TYPES:
                    errors.append(
                        StaticTypeError(
                            message=f"Field '{field_name}' has invalid array item type '{inner_type}'",
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field=f"{config_field}.{field_name}",
                            ),
                            referenced_agent=action_name,
                            referenced_field=field_name,
                            available_fields=self.VALID_TYPES,
                            hint="Use array[string], array[number], etc.",
                        )
                    )
            elif base_type not in self.VALID_TYPES and base_type != "array":
                errors.append(
                    StaticTypeError(
                        message=f"Field '{field_name}' has invalid type '{base_type}'",
                        location=FieldLocation(
                            agent_name=action_name, config_field=f"{config_field}.{field_name}"
                        ),
                        referenced_agent=action_name,
                        referenced_field=field_name,
                        available_fields=self.VALID_TYPES,
                        hint="Valid types: string, number, integer, boolean, array, object",
                    )
                )

        return errors

    def validate_schema_compilability(
        self,
        schema: dict[str, Any],
        action_name: str,
        vendor: str,
    ) -> list[StaticTypeError]:
        """Validate that schema can be compiled for the target vendor."""
        errors: list[StaticTypeError] = []

        if not schema:
            return errors

        try:
            from agent_actions.output.response.schema import compile_unified_schema

            compile_unified_schema(schema, vendor)
        except Exception as e:
            errors.append(
                StaticTypeError(
                    message=f"Schema compilation failed for vendor '{vendor}': {e}",
                    location=FieldLocation(agent_name=action_name, config_field="schema"),
                    referenced_agent=action_name,
                    referenced_field="schema",
                    hint=f"Ensure schema is compatible with {vendor}'s schema format",
                )
            )

        return errors

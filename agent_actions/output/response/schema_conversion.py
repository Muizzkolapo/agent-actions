"""
Schema format conversion utilities.

Converts between JSON Schema format and the unified internal format,
and compiles individual fields for target systems.
"""

import logging
from typing import Any

from agent_actions.errors import SchemaValidationError

logger = logging.getLogger(__name__)


def _convert_json_schema_to_unified(json_schema: dict[str, Any]) -> dict[str, Any]:
    """
    Convert JSON Schema format (type: array) to unified format (fields: [...]).

    Handles schemas like:
    {
        'name': 'candidate_facts_list',
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {'fact': {...}, 'paraphrase': {...}},
            'required': ['fact', 'paraphrase']
        }
    }

    Also supports primitive arrays:
    {
        'name': 'tags',
        'type': 'array',
        'items': {'type': 'string'}
    }

    Converts to unified format by wrapping the array in a field with the schema name.

    Args:
        json_schema: JSON Schema format dictionary with type='array'

    Returns:
        Dictionary in unified format with fields array
    """
    schema_name = json_schema.get("name", "response")
    items = json_schema.get("items", {})

    logger.debug("Converting array-type schema: %s", schema_name)

    # Validation: Check if items is valid - fail fast instead of silent fallback
    if not items or not isinstance(items, dict):
        raise SchemaValidationError(
            f"Array schema '{schema_name}' has empty or invalid 'items' definition",
            schema_name=schema_name,
            validation_type="structure",
            hint=(
                "Array schemas must have an 'items' definition specifying the element type. "
                "Example: items: {type: object, properties: {...}} or items: {type: string}"
            ),
        )

    # Determine whether this array field is required by its parent. The codebase
    # convention is a boolean `required: true|false` at the top level — distinct
    # from JSON Schema's standard `required: [...]` list (which belongs on the
    # OBJECT containing this array, not on the array itself, and never reaches
    # this function because top-level callers strip it).
    #
    # Reject misplaced lists explicitly: previously `required: ['fact', 'paraphrase']`
    # was treated as a truthy boolean and the array was unconditionally required,
    # hiding a config bug. Surface the mistake so the user moves it under `items`.
    required_value = json_schema.get("required", True)
    if isinstance(required_value, bool):
        is_required = required_value
    elif isinstance(required_value, list):
        raise SchemaValidationError(
            f"Array schema '{schema_name}' has a list at top-level 'required'. "
            "A boolean is expected here (whether the array itself is required in "
            "its parent). To declare which item properties are required, move the "
            "list under 'items.required'.",
            schema_name=schema_name,
            validation_type="structure",
            hint=(
                "Replace `required: [field1, field2]` at the array level with "
                "`required: true|false` (this array's requiredness), and put the "
                "property-name list under `items: {required: [field1, field2]}`."
            ),
        )
    else:
        raise SchemaValidationError(
            f"Array schema '{schema_name}' has invalid 'required' value of type "
            f"{type(required_value).__name__}; expected a boolean.",
            schema_name=schema_name,
            validation_type="structure",
            hint="Use `required: true` or `required: false` at the array level.",
        )

    # Items with properties are objects whether or not they say so; without either, the
    # element type is unknown, and guessing object rejects every string the model returns.
    item_type = items.get("type")
    if item_type is None:
        if "properties" not in items:
            raise SchemaValidationError(
                f"Array schema '{schema_name}' has 'items' with no 'type'",
                schema_name=schema_name,
                validation_type="structure",
                hint=(
                    "Say what each element is: items: {type: string} for a list of strings, "
                    "or items: {type: object, properties: {...}} for a list of objects."
                ),
            )
        item_type = "object"

    logger.debug("  - Items type: %s", item_type)

    if item_type == "object":
        # Handle object arrays (existing logic)
        item_properties = items.get("properties", {})
        item_required = items.get("required", [])

        logger.debug("  - Item properties: %s", list(item_properties.keys()))

        fields = [
            {
                "id": schema_name,
                "type": "array",
                "required": is_required,
                "items": {
                    "type": "object",
                    "properties": item_properties,
                    "required": item_required,
                },
            }
        ]
    else:
        # Handle primitive arrays (string, number, boolean, etc.)
        logger.debug("  - Handling primitive array")

        fields = [
            {
                "id": schema_name,
                "type": "array",
                "required": is_required,
                "items": items,  # Pass items as-is for primitives
            }
        ]

    logger.debug("Converted to unified format with %d field(s)", len(fields))

    return {
        "name": schema_name,
        "description": json_schema.get("description", ""),
        "fields": fields,
    }


def _convert_json_schema_object_to_unified(json_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema ``type: object`` to the unified ``fields:`` form.

    The object's properties are the record's fields, exactly as ``fields:``
    entries are, and the top-level ``required`` list is the one ``fields:``
    schemas already honour. ``required`` is JSON Schema's: a property is required
    when it is listed and optional otherwise, whatever the project's
    ``required_by_default`` says.
    """
    schema_name = json_schema.get("name", "response")
    properties = json_schema.get("properties")
    if not isinstance(properties, dict):
        raise SchemaValidationError(
            f"Object schema '{schema_name}' has a 'properties' that is not a mapping",
            schema_name=schema_name,
            validation_type="structure",
            hint="Declare properties as `properties: {field: {type: string}}`.",
        )

    required_value = json_schema.get("required", [])
    if not isinstance(required_value, list):
        raise SchemaValidationError(
            f"Object schema '{schema_name}' has a 'required' of type "
            f"{type(required_value).__name__}; expected a list of property names.",
            schema_name=schema_name,
            validation_type="structure",
            hint="Use `required: [field1, field2]` naming properties declared above.",
        )
    undeclared = [name for name in required_value if name not in properties]
    if undeclared:
        raise SchemaValidationError(
            f"Object schema '{schema_name}' lists required "
            f"{', '.join(repr(n) for n in undeclared)} that are not in 'properties'.",
            schema_name=schema_name,
            validation_type="structure",
            hint="Every name in `required:` must be a key under `properties:`.",
        )

    for prop_name, prop in properties.items():
        if not isinstance(prop, dict) or "type" not in prop:
            raise SchemaValidationError(
                f"Property '{prop_name}' of object schema '{schema_name}' has no 'type'",
                schema_name=schema_name,
                validation_type="structure",
                hint=f"Declare it as `{prop_name}: {{type: string}}`.",
            )

    unified: dict[str, Any] = {
        "name": schema_name,
        "description": json_schema.get("description", ""),
        "fields": [{**prop, "id": name} for name, prop in properties.items()],
        "required": required_value,
        "required_by_default": False,
    }
    if "additionalProperties" in json_schema:
        unified["additionalProperties"] = json_schema["additionalProperties"]
    return unified


def _without_rules(node: Any) -> Any:
    """A schema node with any expectations: block removed, at every depth.

    Rules ride in the schema file for the author's benefit; the provider is sent
    the shape only, and a nested block would otherwise be copied through with
    the structure that carries it.
    """
    if isinstance(node, dict):
        return {k: _without_rules(v) for k, v in node.items() if k != "expectations"}
    if isinstance(node, list):
        return [_without_rules(item) for item in node]
    return node


def compile_field(field: dict[str, Any], target_system: str) -> tuple[str, dict]:
    """
    Convert a single unified field into the shape required by the target system.
    If custom name-mappings exist for that system, apply them.

    Supports both unified format (id) and docs format (name) for field identifier.
    """
    # Support both 'id' (unified format) and 'name' (docs format) for field identifier
    field_id = field.get("id") or field.get("name")
    if not field_id:
        raise KeyError(f"Field missing both 'id' and 'name' keys: {field}")
    target_field = field.get("mappings", {}).get(target_system.lower(), field_id)
    prop: dict[str, Any] = {"type": field["type"]}
    for k in ("title", "description", "pattern", "minItems", "maxItems"):
        if k in field:
            prop[k] = field[k]
    if field["type"] == "array" and "items" in field:
        prop["items"] = _without_rules(field["items"])
    if field["type"] == "object":
        for k in ("properties", "additionalProperties"):
            if k in field:
                prop[k] = _without_rules(field[k])
        if isinstance(field.get("required"), list):
            prop["required"] = list(field["required"])
    if "enum" in field:
        prop["enum"] = field["enum"]
    if "validators" in field:
        for v in field["validators"]:
            if "not" in v:
                prop["not"] = v["not"]
                if "errorMessage" in v:
                    prop["errorMessage"] = v["errorMessage"]
    return (target_field, prop)

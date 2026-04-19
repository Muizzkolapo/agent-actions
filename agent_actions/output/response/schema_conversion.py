"""
Schema format conversion utilities.

Converts between JSON Schema format and the unified internal format,
and compiles individual fields for target systems.
"""

import logging
import math
from datetime import date, datetime
from typing import Any

from agent_actions.errors import SchemaValidationError

logger = logging.getLogger(__name__)


def _sanitise_schema_value(obj: Any) -> Any:
    """Recursively sanitise schema values for JSON serialisation.

    Schema definitions parsed from YAML can contain Python-specific types
    (``datetime.date`` from bare date literals, ``float('nan')`` from ``.nan``)
    and dispatch functions can return arbitrary types.  This ensures every
    value in the compiled schema is safe for ``json.dumps()``.
    """
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            logger.warning("Replacing non-finite float %r with null in schema value", obj)
            return None
        return obj
    if isinstance(obj, dict):
        return {str(k): _sanitise_schema_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitise_schema_value(item) for item in obj]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (set, frozenset)):
        return [_sanitise_schema_value(item) for item in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    logger.warning(
        "Converting non-serializable type %s to string in schema value",
        type(obj).__name__,
    )
    return str(obj)


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

    # Check if array is required (default to True for backward compatibility)
    is_required = json_schema.get("required", True)

    # Determine if items are objects or primitives
    item_type = items.get("type", "object")

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
            prop[k] = _sanitise_schema_value(field[k])
    if field["type"] == "array" and "items" in field:
        prop["items"] = _sanitise_schema_value(field["items"])
    if "enum" in field:
        prop["enum"] = _sanitise_schema_value(field["enum"])
    if "validators" in field:
        for v in field["validators"]:
            if "not" in v:
                prop["not"] = _sanitise_schema_value(v["not"])
                if "errorMessage" in v:
                    prop["errorMessage"] = _sanitise_schema_value(v["errorMessage"])
    return (target_field, prop)

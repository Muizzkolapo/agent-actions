"""Schema compilation and transformation utilities for multi-vendor support.

This module provides utilities for converting unified schema definitions into
vendor-specific formats (OpenAI, Anthropic, Gemini, Ollama) and handling
JSON Schema to unified format conversions.
"""

from typing import Tuple, Dict, Any, Optional, Union
import json
import logging
from agent_actions.errors import ConfigValidationError
from agent_actions.prompt_generation.prompt_utils import PromptUtils
from agent_actions.utilities.constants import SCHEMA_KEY, SCHEMA_NAME_KEY
from agent_actions.response_processing.schema_loader import SchemaLoader

logger = logging.getLogger(__name__)


def _convert_json_schema_to_unified(json_schema: Dict[str, Any]) -> Dict[str, Any]:
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

    # Validation: Check if items is valid
    if not items or not isinstance(items, dict):
        logger.warning(
            "Array schema '%s' has empty or invalid 'items'. Creating fallback structure.",
            schema_name,
        )
        # Create a minimal valid fallback
        fields = [
            {
                "id": schema_name,
                "type": "array",
                "required": json_schema.get("required", True),
                "items": {"type": "object", "properties": {}, "required": []},
            }
        ]
        return {
            "name": schema_name,
            "description": json_schema.get("description", ""),
            "fields": fields,
        }

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


def compile_field(field: Dict[str, Any], target_system: str) -> Tuple[str, Dict]:
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
    prop: Dict[str, Any] = {"type": field["type"]}
    for k in ("title", "description", "pattern", "minItems", "maxItems"):
        if k in field:
            prop[k] = field[k]
    if field["type"] == "array" and "items" in field:
        prop["items"] = field["items"]
    if "enum" in field:
        prop["enum"] = field["enum"]
    if "validators" in field:
        for v in field["validators"]:
            if "not" in v:
                prop["not"] = v["not"]
                if "errorMessage" in v:
                    prop["errorMessage"] = v["errorMessage"]
    return (target_field, prop)


def compile_unified_schema(unified: Dict[str, Any], target_system: str) -> Dict[str, Any]:
    """
    Convert a unified YAML/JSON definition into the schema dialect required by
    OpenAI, Anthropic, Gemini, **or Ollama** (new).

    Handles two schema formats:
    1. Unified format: {'name': '...', 'fields': [{id: 'field', type: 'string'}, ...]}
    2. JSON Schema format: {'name': '...', 'type': 'array', 'items': {...}}
    """
    # Check if this is a JSON Schema format (type: array)
    # instead of unified format (fields: [...])
    if (
        "type" in unified
        and unified.get("type") == "array"
        and "items" in unified
        and "fields" not in unified
    ):
        # This is a JSON Schema array format - convert to unified format
        logger.debug(
            "Converting JSON Schema array format to unified format for schema: %s",
            unified.get("name", "unknown"),
        )
        unified = _convert_json_schema_to_unified(unified)

    properties: Dict[str, Any] = {}
    required: list[str] = []
    for field in unified.get("fields", []):
        key, schema_prop = compile_field(field, target_system)
        properties[key] = schema_prop
        if field.get("required", False):
            required.append(key)
    target = target_system.lower()
    if target == "openai":
        compiled = {
            "name": unified.get("name", ""),
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        }
    elif target == "anthropic":
        compiled = [
            {
                "name": unified.get("name", ""),
                "description": unified.get("description", ""),
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        ]
    elif target == "gemini":
        compiled = {"name": unified.get("name", ""), "schema": properties}
    elif target == "ollama":
        compiled = {
            "title": unified.get("name", ""),
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
    else:
        raise ConfigValidationError(
            "target_system",
            f"Unknown target system: {target}",
            context={
                "target_system": target,
                "valid_systems": ["openai", "anthropic", "gemini", "ollama"],
                "operation": "compile_unified_schema",
            },
        )
    return compiled


def _inject_functions_into_schema(
    schema: Any,
    tools_path: Optional[str],
    context_data_str: Optional[str],
    agent_config: Optional[Dict[str, Any]],
    captured_results: Dict[str, Any],
) -> Any:  # pylint: disable=too-many-branches
    """
    Recursively traverse schema and replace dispatch_task() calls.

    Args:
        schema: The schema object (dict, list, or primitive)
        tools_path: Path to tools directory
        context_data_str: Context data for functions
        agent_config: Agent configuration
        captured_results: Dictionary to collect function outputs (add_dispatch)

    Returns:
        The processed schema with function outputs injected
    """
    if isinstance(schema, dict):
        return {
            k: _inject_functions_into_schema(
                v, tools_path, context_data_str, agent_config, captured_results
            )
            for k, v in schema.items()
        }
    if isinstance(schema, list):
        return [
            _inject_functions_into_schema(
                item, tools_path, context_data_str, agent_config, captured_results
            )
            for item in schema
        ]
    if isinstance(schema, str):
        # Only process strings containing dispatch_task
        if "dispatch_task(" in schema:
            return PromptUtils.process_dispatch_in_text(
                schema,
                tools_path=tools_path,
                context_data_str=context_data_str,
                agent_config=agent_config,
                captured_results=captured_results,
                preserve_type_on_exact_match=True,
            )
        return schema
    return schema


def prepare_schema_unified(  # pylint: disable=too-many-branches
    agent_config: Dict[str, Any],
    vendor: str,
    tools_path: Optional[str] = None,
    context_data: Optional[Union[Dict, str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Unified schema preparation for both online and batch modes.

    This function provides a single code path for schema compilation across
    the entire system, ensuring consistent behavior and validation regardless
    of whether the agent is running in online or batch mode.

    Args:
        agent_config: Agent configuration dictionary containing schema settings
        vendor: Vendor name (e.g., 'openai', 'anthropic', 'gemini', 'ollama')
        tools_path: Path to tools directory (optional, for dispatch_task)
        context_data: Context data for dispatch_task (optional)

    Returns:
        Tuple containing:
        1. Compiled schema in vendor-specific format (or None)
        2. Captured results from dispatch_task (if add_dispatch is enabled)

    Side Effects:
        Logs a WARNING if schema is requested but vendor doesn't support it
    """
    captured_results = {}

    if vendor == "tool":
        return None, captured_results

    # Prepare context_data_str if tools_path is provided, as it might be needed early
    context_data_str = "{}"
    if tools_path:
        if isinstance(context_data, (dict, list)):
            context_data_str = json.dumps(context_data, ensure_ascii=False)
        else:
            context_data_str = str(context_data or "{}")

    inline_schema = agent_config.get(SCHEMA_KEY)

    if inline_schema:
        # Resolve dispatch if the top-level schema itself is a dispatch call
        if isinstance(inline_schema, str) and "dispatch_task(" in inline_schema:
            try:
                inline_schema = PromptUtils.process_dispatch_in_text(
                    inline_schema,
                    tools_path=tools_path,
                    context_data_str=context_data_str,
                    agent_config=agent_config,
                    captured_results=captured_results,
                    preserve_type_on_exact_match=True,
                )
            except (ValueError, TypeError, KeyError) as e:
                # Let downstream validation handle it if it fails or returns None
                logger.debug("dispatch_task resolution failed, deferring to downstream: %s", e)

        # Check if the resolved schema is already in unified format (has 'fields' list)
        if (
            isinstance(inline_schema, dict)
            and "fields" in inline_schema
            and isinstance(inline_schema["fields"], list)
        ):
            base_schema = inline_schema
        else:
            base_schema = SchemaLoader.construct_schema_from_dict(inline_schema)

        schema_name = agent_config.get("name", "inline_schema")
    else:
        schema_name = agent_config.get(SCHEMA_NAME_KEY)
        if not schema_name:
            return None, captured_results
        base_schema = SchemaLoader.load_schema(schema_name)

    # Inject functions into the constructed schema
    # (This handles recursion and fields within the loaded/constructed schema)
    if tools_path:  # Only inject if tools_path is provided
        base_schema = _inject_functions_into_schema(
            base_schema,
            tools_path=tools_path,
            context_data_str=context_data_str,
            agent_config=agent_config,
            captured_results=captured_results,
        )

    # Unwrap schema if it is nested (common pattern in loaded yaml files with 'schema' key)
    # E.g. {name: '...', schema: {name: '...', fields: [...]}} -> {name: '...', fields: [...]}
    if (
        isinstance(base_schema, dict)
        and SCHEMA_KEY in base_schema
        and isinstance(base_schema[SCHEMA_KEY], dict)
    ):
        nested_schema = base_schema[SCHEMA_KEY]
        # Verify if nested schema looks like a unified schema (has fields)
        # or a JSON schema (type: object/array)
        if "fields" in nested_schema or "type" in nested_schema:
            # Merge top-level metadata (name, description) if missing in nested
            if "name" not in nested_schema and "name" in base_schema:
                nested_schema["name"] = base_schema["name"]
            base_schema = nested_schema

    try:
        return compile_unified_schema(base_schema, vendor), captured_results
    except ConfigValidationError:
        logger.warning(
            "Vendor '%s' does not support schema validation. Schema '%s' will be ignored. "
            "For schema support, use one of: openai, anthropic, gemini, ollama",
            vendor,
            schema_name,
        )
        return None, captured_results

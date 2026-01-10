"""
Schema compilation and transformation utilities for multi-vendor support.
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
) -> Any:
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


def _prepare_context_data_str(
    context_data: Optional[Union[Dict, str]],
    tools_path: Optional[str],
) -> str:
    """
    Prepare context data as JSON string for dispatch_task processing.

    Args:
        context_data: Context data (dict, list, or string)
        tools_path: Path to tools directory

    Returns:
        JSON string representation of context data
    """
    if not tools_path:
        return "{}"
    if isinstance(context_data, (dict, list)):
        return json.dumps(context_data, ensure_ascii=False)
    return str(context_data or "{}")


def _resolve_dispatch_in_schema(
    schema: Any,
    tools_path: Optional[str],
    context_data_str: str,
    agent_config: Dict[str, Any],
    captured_results: Dict[str, Any],
) -> Any:
    """
    Resolve dispatch_task calls in schema string.

    Args:
        schema: Schema value (may be string with dispatch_task)
        tools_path: Path to tools directory
        context_data_str: Context data as JSON string
        agent_config: Agent configuration
        captured_results: Dictionary to collect function outputs

    Returns:
        Resolved schema (original if not a dispatch call or resolution fails)
    """
    if not isinstance(schema, str) or "dispatch_task(" not in schema:
        return schema

    try:
        return PromptUtils.process_dispatch_in_text(
            schema,
            tools_path=tools_path,
            context_data_str=context_data_str,
            agent_config=agent_config,
            captured_results=captured_results,
            preserve_type_on_exact_match=True,
        )
    except (ValueError, TypeError, KeyError) as e:
        logger.debug("dispatch_task resolution failed, deferring to downstream: %s", e)
        return schema


def _is_unified_format(schema: Any) -> bool:
    """Check if schema is already in unified format with 'fields' list."""
    return isinstance(schema, dict) and "fields" in schema and isinstance(schema["fields"], list)


def _load_inline_schema(
    inline_schema: Any,
    tools_path: Optional[str],
    context_data_str: str,
    agent_config: Dict[str, Any],
    captured_results: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
    """
    Load and prepare inline schema from agent config.

    Args:
        inline_schema: Raw inline schema from config
        tools_path: Path to tools directory
        context_data_str: Context data as JSON string
        agent_config: Agent configuration
        captured_results: Dictionary to collect function outputs

    Returns:
        Tuple of (prepared schema dict, schema name)
    """
    # Resolve dispatch if schema is a dispatch call string
    resolved_schema = _resolve_dispatch_in_schema(
        inline_schema, tools_path, context_data_str, agent_config, captured_results
    )

    # Convert to unified format if needed
    if _is_unified_format(resolved_schema):
        base_schema = resolved_schema
    else:
        base_schema = SchemaLoader.construct_schema_from_dict(resolved_schema)

    schema_name = agent_config.get("name", "inline_schema")
    return base_schema, schema_name


def _load_named_schema(agent_config: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Load schema by name from schema store.

    Args:
        agent_config: Agent configuration with schema_name

    Returns:
        Tuple of (schema dict or None, schema name)
    """
    schema_name = agent_config.get(SCHEMA_NAME_KEY)
    if not schema_name:
        return None, ""
    return SchemaLoader.load_schema(schema_name), schema_name


def _unwrap_nested_schema(base_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unwrap nested schema structure if present.

    Handles pattern: {name: '...', schema: {name: '...', fields: [...]}}
    Converts to: {name: '...', fields: [...]}

    Args:
        base_schema: Schema dict that may have nested 'schema' key

    Returns:
        Unwrapped schema dict
    """
    if not isinstance(base_schema, dict):
        return base_schema

    if SCHEMA_KEY not in base_schema:
        return base_schema

    nested_schema = base_schema[SCHEMA_KEY]
    if not isinstance(nested_schema, dict):
        return base_schema

    # Only unwrap if nested schema looks like unified or JSON schema
    if "fields" not in nested_schema and "type" not in nested_schema:
        return base_schema

    # Merge top-level name if missing in nested
    if "name" not in nested_schema and "name" in base_schema:
        nested_schema["name"] = base_schema["name"]

    return nested_schema


def _compile_schema_for_vendor(
    base_schema: Dict[str, Any],
    vendor: str,
    schema_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Compile schema for specific vendor with error handling.

    Args:
        base_schema: Unified schema dict
        vendor: Target vendor name
        schema_name: Schema name for logging

    Returns:
        Compiled schema or None if vendor doesn't support schemas
    """
    try:
        return compile_unified_schema(base_schema, vendor)
    except ConfigValidationError:
        logger.warning(
            "Vendor '%s' does not support schema validation. Schema '%s' will be ignored. "
            "For schema support, use one of: openai, anthropic, gemini, ollama",
            vendor,
            schema_name,
        )
        return None


def prepare_schema_unified(
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
    captured_results: Dict[str, Any] = {}

    # Tool vendor doesn't use schemas
    if vendor == "tool":
        return None, captured_results

    # Prepare context string for dispatch resolution
    context_data_str = _prepare_context_data_str(context_data, tools_path)

    # Load schema (inline or named)
    inline_schema = agent_config.get(SCHEMA_KEY)
    if inline_schema:
        base_schema, schema_name = _load_inline_schema(
            inline_schema, tools_path, context_data_str, agent_config, captured_results
        )
    else:
        base_schema, schema_name = _load_named_schema(agent_config)
        if base_schema is None:
            return None, captured_results

    # Inject dispatch_task functions into schema fields
    if tools_path:
        base_schema = _inject_functions_into_schema(
            base_schema,
            tools_path=tools_path,
            context_data_str=context_data_str,
            agent_config=agent_config,
            captured_results=captured_results,
        )

    # Unwrap nested schema structure if present
    base_schema = _unwrap_nested_schema(base_schema)

    # Compile for target vendor
    compiled = _compile_schema_for_vendor(base_schema, vendor, schema_name)
    return compiled, captured_results

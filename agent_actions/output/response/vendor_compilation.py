"""
Vendor-specific schema compilation.

Compiles unified schemas into the format required by each LLM vendor
(OpenAI, Anthropic, Gemini, Ollama, Groq, Cohere, etc.).
"""

import logging
from typing import Any

from agent_actions.config.schema_field import field_is_required, top_level_required_ids
from agent_actions.errors import ConfigValidationError
from agent_actions.utils.json_safety import ensure_json_safe

from .schema_conversion import _convert_json_schema_to_unified, compile_field

logger = logging.getLogger(__name__)

# Vendors with schema/tool-calling support. Caller `_compile_schema_for_vendor`
# pre-checks this set so unknown vendors short-circuit to None without going
# through `compile_unified_schema` — keeping the ConfigValidationError catch
# surface narrow to genuine validation errors.
SUPPORTED_VENDORS: frozenset[str] = frozenset(
    {
        "openai",
        "anthropic",
        "gemini",
        "ollama_local",
        "ollama_cloud",
        "agac-provider",
        "groq",
        "cohere",
    }
)


def compile_unified_schema(
    unified: dict[str, Any], target_system: str
) -> dict[str, Any] | list[dict[str, Any]]:
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

    properties: dict[str, Any] = {}
    required: list[str] = []
    required_by_default = unified.get("required_by_default", False)
    top_level_required = top_level_required_ids(unified)
    for field in unified.get("fields", []):
        key, schema_prop = compile_field(field, target_system)
        properties[key] = schema_prop
        if field_is_required(field, required_by_default, top_level_required):
            required.append(key)
    target = target_system.lower()
    compiled: dict[str, Any] | list[dict[str, Any]]
    if target in ("openai", "groq", "agac-provider"):
        # OpenAI-compatible format — Groq and agac-provider use the same shape
        compiled = {
            "name": unified.get("name", ""),
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": unified.get("additionalProperties", False),
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
                    "additionalProperties": unified.get("additionalProperties", False),
                },
            }
        ]
    elif target == "gemini":
        compiled = {
            "name": unified.get("name", ""),
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
    elif target in {"ollama_local", "ollama_cloud"}:
        compiled = {
            "title": unified.get("name", ""),
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": unified.get("additionalProperties", False),
        }
    elif target == "cohere":
        # Cohere native format
        compiled = {
            "type": "object",
            "properties": properties,
            "required": required,
        }
    else:
        raise ConfigValidationError(
            "target_system",
            f"Unknown target system: {target}",
            context={
                "target_system": target,
                "valid_systems": sorted(SUPPORTED_VENDORS),
                "operation": "compile_unified_schema",
            },
        )
    sanitised: dict[str, Any] | list[dict[str, Any]] = ensure_json_safe(compiled)
    return sanitised

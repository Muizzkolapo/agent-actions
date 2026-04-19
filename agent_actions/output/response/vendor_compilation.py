"""
Vendor-specific schema compilation.

Compiles unified schemas into the format required by each LLM vendor
(OpenAI, Anthropic, Gemini, Ollama, Groq, Mistral, Cohere, etc.).
"""

import logging
from typing import Any

from agent_actions.errors import ConfigValidationError

from .schema_conversion import (
    _convert_json_schema_to_unified,
    _sanitise_schema_value,
    compile_field,
)

logger = logging.getLogger(__name__)


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
    for field in unified.get("fields", []):
        key, schema_prop = compile_field(field, target_system)
        properties[key] = schema_prop
        if field.get("required", False):
            required.append(key)
    target = target_system.lower()
    compiled: dict[str, Any] | list[dict[str, Any]]
    if target in ("openai", "groq", "mistral", "agac-provider"):
        # OpenAI-compatible format — Groq, Mistral, and agac-provider use the same shape
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
        compiled = {
            "name": unified.get("name", ""),
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
    elif target == "ollama":
        compiled = {
            "title": unified.get("name", ""),
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
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
                "valid_systems": [
                    "openai",
                    "anthropic",
                    "gemini",
                    "ollama",
                    "agac-provider",
                    "groq",
                    "mistral",
                    "cohere",
                ],
                "operation": "compile_unified_schema",
            },
        )
    return _sanitise_schema_value(compiled)

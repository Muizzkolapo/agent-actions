"""
Context data handling for schema preparation.

Provides helper functions for context data preparation, schema loading/unwrapping,
and vendor compilation that support the unified schema preparation pipeline.
"""

import json
import logging
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigValidationError
from agent_actions.output.response.loader import SchemaLoader
from agent_actions.utils.constants import SCHEMA_KEY, SCHEMA_NAME_KEY

from .dispatch_injection import _resolve_dispatch_in_schema
from .vendor_compilation import compile_unified_schema

logger = logging.getLogger(__name__)


def _prepare_context_data_str(
    context_data: dict | str | None,
    tools_path: str | None,
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
    if isinstance(context_data, dict | list):
        return json.dumps(context_data, ensure_ascii=False)
    return str(context_data or "{}")


def _is_unified_format(schema: Any) -> bool:
    """Check if schema is already in unified format with 'fields' list."""
    return isinstance(schema, dict) and "fields" in schema and isinstance(schema["fields"], list)


def _load_inline_schema(
    inline_schema: Any,
    tools_path: str | None,
    context_data_str: str,
    agent_config: dict[str, Any],
    captured_results: dict[str, Any],
) -> tuple[dict[str, Any], str]:
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


def _load_named_schema(
    agent_config: dict[str, Any], project_root: Path | None = None
) -> tuple[dict[str, Any] | None, str]:
    """
    Load schema by name from schema store.

    Args:
        agent_config: Agent configuration with schema_name
        project_root: Optional project root for schema directory resolution

    Returns:
        Tuple of (schema dict or None, schema name)
    """
    schema_name = agent_config.get(SCHEMA_NAME_KEY)
    if not schema_name:
        return None, ""
    return SchemaLoader.load_schema(schema_name, project_root=project_root), schema_name


def _unwrap_nested_schema(base_schema: dict[str, Any]) -> dict[str, Any]:
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
        return base_schema  # type: ignore[unreachable]

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
    base_schema: dict[str, Any],
    vendor: str,
    schema_name: str,
) -> dict[str, Any] | list[dict[str, Any]] | None:
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
            "For schema support, use one of: openai, anthropic, gemini, ollama, groq, mistral, cohere, agac-provider",
            vendor,
            schema_name,
        )
        return None

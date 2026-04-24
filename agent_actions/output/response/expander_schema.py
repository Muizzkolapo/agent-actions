"""Schema processing functions extracted from ActionExpander."""

import logging
from typing import Any

from agent_actions.errors import SchemaValidationError
from agent_actions.output.response.schema import compile_unified_schema
from agent_actions.utils.schema_utils import is_compiled_schema

logger = logging.getLogger(__name__)


def process_schema_config(agent: dict[str, Any], action: dict[str, Any], template_replacer) -> None:
    """
    Process schema configuration for an agent.

    If the schema is already compiled (from render step), use it directly.
    Otherwise, apply template replacement and set appropriately.
    """
    schema_value = action.get("schema")
    if schema_value:
        # If already compiled (unified format from render step), use directly
        if is_compiled_schema(schema_value):
            agent["schema"] = schema_value
        else:
            # Apply template replacement for non-compiled schemas
            schema_value = template_replacer(schema_value)
            if isinstance(schema_value, str):
                agent["schema_name"] = schema_value
            elif isinstance(schema_value, dict):
                agent["schema"] = schema_value
            else:
                agent["schema"] = schema_value


def compile_output_schema(agent: dict[str, Any], action: dict[str, Any]) -> None:
    """Compile YAML schema: to json_output_schema for any action type.

    Skips if json_output_schema is already set (e.g. from HITL
    auto-injection), so action-type-specific schemas take precedence.
    """
    # Skip if already has json_output_schema
    if agent.get("json_output_schema"):
        return

    # Get schema from action (already processed by process_schema_config)
    schema_fields = agent.get("schema")
    if not schema_fields:
        return

    # Build unified schema format
    agent_name = agent["agent_type"]

    # Handle list of fields format: [{id: 'field', type: 'string'}, ...]
    if isinstance(schema_fields, list):
        unified_schema = {"name": agent_name, "fields": schema_fields}
    # Handle dict format (already unified or JSON Schema)
    elif isinstance(schema_fields, dict):
        if "fields" in schema_fields:
            unified_schema = schema_fields
        else:
            # Assume it's a JSON Schema format - compile_unified_schema handles this
            unified_schema = {"name": agent_name, **schema_fields}
    else:
        logger.warning(
            "Action '%s' has schema of unsupported type '%s' (expected list or dict). "
            "Schema will be ignored.",
            agent_name,
            type(schema_fields).__name__,
        )
        return

    # For array-type schemas, json_output_schema describes a single item.
    # The full unified schema is kept in output_schema for LLM providers.
    if (
        isinstance(schema_fields, dict)
        and schema_fields.get("type") == "array"
        and "items" in schema_fields
        and "fields" not in schema_fields
    ):
        items_schema = schema_fields["items"]
        if isinstance(items_schema, dict) and items_schema.get("type") == "object":
            items_schema.setdefault("additionalProperties", False)
        agent["output_schema"] = unified_schema
        agent["json_output_schema"] = items_schema
        return

    # Compile to JSON Schema for validation
    try:
        # Use 'openai' format as canonical JSON Schema
        compiled = compile_unified_schema(unified_schema, "openai")
        agent["output_schema"] = unified_schema
        # isinstance guard: compile_unified_schema returns list for Anthropic target,
        # but we always pass "openai" here so compiled is always dict. Guard satisfies mypy.
        agent["json_output_schema"] = (
            compiled.get("schema", compiled) if isinstance(compiled, dict) else compiled
        )
    except (ValueError, KeyError, TypeError) as e:
        raise SchemaValidationError(
            f"Failed to compile output schema for action '{agent_name}'",
            schema_name=agent_name,
            validation_type="compilation",
            hint="Check that schema: fields have valid 'id' and 'type' entries.",
            cause=e,
        ) from e

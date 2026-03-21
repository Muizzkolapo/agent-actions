"""
Response schema compiler for multi-vendor LLM support.

Compiles action response schemas into vendor-specific formats (OpenAI,
Anthropic, Gemini, etc.).  Implementation delegates to focused submodules:

- schema_conversion: JSON Schema to unified format, field compilation
- vendor_compilation: Vendor-specific schema compilation
- dispatch_injection: dispatch_task() resolution and injection
- context_data: Context data handling, schema loading/unwrapping helpers
"""

import logging
from pathlib import Path
from typing import Any

from agent_actions.output.response.context_data import (  # noqa: F401
    _compile_schema_for_vendor,
    _is_unified_format,
    _load_inline_schema,
    _load_named_schema,
    _prepare_context_data_str,
    _unwrap_nested_schema,
)
from agent_actions.output.response.dispatch_injection import (  # noqa: F401
    _inject_functions_into_schema,
    _resolve_dispatch_in_schema,
)
from agent_actions.output.response.schema_conversion import (  # noqa: F401
    _convert_json_schema_to_unified,
    compile_field,
)
from agent_actions.output.response.vendor_compilation import (  # noqa: F401
    compile_unified_schema,
)
from agent_actions.utils.constants import SCHEMA_KEY

logger = logging.getLogger(__name__)


class ResponseSchemaCompiler:
    """Compiles action response schemas into vendor-specific LLM formats.

    Holds stable per-workflow state (project_root, tools_path) and exposes
    a ``compile()`` method for per-action schema compilation.
    """

    def __init__(
        self,
        project_root: Path | None = None,
        tools_path: str | None = None,
    ):
        self._project_root = project_root
        self._tools_path = tools_path

    def compile(
        self,
        agent_config: dict[str, Any],
        vendor: str,
        context_data: dict | str | None = None,
    ) -> tuple[dict[str, Any] | list[dict[str, Any]] | None, dict[str, Any]]:
        """Load, resolve, and compile a response schema for a target vendor.

        Args:
            agent_config: Agent configuration dictionary containing schema settings
            vendor: Vendor name (e.g., 'openai', 'anthropic', 'gemini', 'ollama')
            context_data: Context data for dispatch_task (optional)

        Returns:
            Tuple of (compiled schema in vendor format or None, captured dispatch results)
        """
        captured_results: dict[str, Any] = {}

        # Tool vendor doesn't use schemas
        if vendor == "tool":
            return None, captured_results

        # Prepare context string for dispatch resolution
        context_data_str = _prepare_context_data_str(context_data, self._tools_path)

        # Load schema (inline or named)
        inline_schema = agent_config.get(SCHEMA_KEY)
        if inline_schema:
            base_schema, schema_name = _load_inline_schema(
                inline_schema,
                self._tools_path,
                context_data_str,
                agent_config,
                captured_results,
            )
        else:
            loaded_schema, schema_name = _load_named_schema(
                agent_config, project_root=self._project_root
            )
            if loaded_schema is None:
                return None, captured_results
            base_schema = loaded_schema

        # Inject dispatch_task functions into schema fields
        if self._tools_path:
            base_schema = _inject_functions_into_schema(
                base_schema,
                tools_path=self._tools_path,
                context_data_str=context_data_str,
                agent_config=agent_config,
                captured_results=captured_results,
            )

        # Unwrap nested schema structure if present
        base_schema = _unwrap_nested_schema(base_schema)

        # Compile for target vendor
        compiled = _compile_schema_for_vendor(base_schema, vendor, schema_name)
        if compiled is None and (inline_schema or agent_config.get("schema_name")):
            logger.warning(
                "Schema '%s' was explicitly configured but vendor '%s' does not support "
                "schema validation. LLM responses will not be schema-constrained.",
                schema_name,
                vendor,
            )
        return compiled, captured_results

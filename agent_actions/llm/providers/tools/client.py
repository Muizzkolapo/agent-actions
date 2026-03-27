"""
Tool client for executing user-defined functions.

This module provides the ToolClient for invoking custom user-defined
functions (UDFs) as part of the agent-actions LLM invocation pipeline.
"""

import json
from typing import Any, ClassVar

from agent_actions.utils.constants import MODEL_NAME_KEY
from agent_actions.utils.udf_management.tooling import execute_user_defined_function


class ToolClient:
    """Client for executing user-defined functions as LLM clients."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": False,
        "supports_vision": False,
        "required_fields": [],
        "optional_fields": ["tool_name"],
    }

    @staticmethod
    def _strip_internal_fields(data: str | dict | list) -> str | dict | list:
        """Strip internal metadata fields from context data before UDF invocation.

        Internal fields like batch_id, source_guid, node_id, _batch_filter_status
        are tracking metadata and should not be passed to user-defined functions.

        Args:
            data: Context data (str, dict, or list of dicts for FILE mode)

        Returns:
            Cleaned data with internal fields removed
        """
        from agent_actions.llm.batch.core.batch_context_metadata import (
            BatchContextMetadata,
        )

        strip = BatchContextMetadata.strip_internal_fields

        if isinstance(data, list):
            return [strip(item) if isinstance(item, dict) else item for item in data]

        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    return json.dumps(strip(parsed))
                return data
            except (json.JSONDecodeError, TypeError):
                return data

        if isinstance(data, dict):
            return strip(data)  # type: ignore[return-value, no-any-return]

        return data  # type: ignore[unreachable]

    @staticmethod
    def invoke(
        agent_config: dict[str, Any],
        context_data: str | dict,
        tool_args: dict[str, Any] | None = None,
        source_content: Any | None = None,
    ) -> Any:
        """
        Invoke a user-defined function (UDF) specified in the configuration.
        """
        model_name = agent_config.get(MODEL_NAME_KEY)
        if not model_name:
            from agent_actions.errors import ConfigurationError

            raise ConfigurationError(
                "Tool vendor requires 'model_name' (UDF path) in agent config",
                context={
                    "vendor": "tool",
                    "missing_field": "model_name",
                    "agent_config_keys": list(agent_config.keys()),
                },
            )

        # Strip internal metadata fields before passing to UDF
        clean_context = ToolClient._strip_internal_fields(context_data)

        udf_kwargs = tool_args if tool_args is not None else {}
        response = execute_user_defined_function(
            model_name,
            clean_context,  # type: ignore[arg-type]
            json_output_schema=agent_config.get("json_output_schema"),
            **udf_kwargs,
        )
        if isinstance(response, str):
            return json.loads(response)
        return response

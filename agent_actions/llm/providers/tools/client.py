"""
Tool client for executing user-defined functions.

This module provides the ToolClient for invoking custom user-defined
functions (UDFs) as part of the agent-actions LLM invocation pipeline.
"""

import json
from typing import Dict, Any, Optional, Union

from agent_actions.utils.constants import MODEL_NAME_KEY
from agent_actions.utils.udf_management.tooling import execute_user_defined_function


class ToolClient:
    """Client for executing user-defined functions as LLM clients."""

    @staticmethod
    def _strip_internal_fields(data: Union[str, Dict]) -> Union[str, Dict]:
        """Strip internal metadata fields from context data before UDF invocation.

        Internal fields like batch_id, source_guid, node_id, _batch_filter_status
        are tracking metadata and should not be passed to user-defined functions.

        Args:
            data: Context data (str or dict)

        Returns:
            Cleaned data with internal fields removed
        """
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    from agent_actions.llm.batch.core.batch_context_metadata import (
                        BatchContextMetadata,
                    )

                    cleaned = BatchContextMetadata.strip_internal_fields(parsed)
                    return json.dumps(cleaned)
                return data
            except (json.JSONDecodeError, TypeError):
                return data

        if isinstance(data, dict):
            from agent_actions.llm.batch.core.batch_context_metadata import (
                BatchContextMetadata,
            )

            return BatchContextMetadata.strip_internal_fields(data)

        return data

    @staticmethod
    def invoke(
        agent_config: Dict[str, Any],
        context_data: Union[str, Dict],
        tool_args: Optional[Dict[str, Any]] = None,
        source_content: Optional[Any] = None,
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

        side_output = agent_config.get("side_output", False)
        udf_kwargs = tool_args if tool_args is not None else {}
        response = execute_user_defined_function(model_name, clean_context, **udf_kwargs)
        if side_output:
            condition, result = response
            if condition:
                return {"result": json.loads(result), "side_output": True}
            return json.loads(result)
        if isinstance(response, str):
            return json.loads(response)
        return response

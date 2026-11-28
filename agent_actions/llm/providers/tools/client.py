"""
Tool client for executing user-defined functions.

This module provides the ToolClient for invoking custom user-defined
functions (UDFs) as part of the agent-actions LLM invocation pipeline.
"""

import json
from typing import TYPE_CHECKING, Any, ClassVar

from agent_actions.config import sandbox
from agent_actions.llm.providers.tools.builtin import MCP, builtin_tool, run_builtin
from agent_actions.utils.constants import MODEL_NAME_KEY, RECORD_GUID_KEY
from agent_actions.utils.udf_management.tooling import (
    execute_user_defined_function,
    output_schema_errors,
)

if TYPE_CHECKING:
    from agent_actions.llm.providers.agac.scenario import Scenario


class ToolClient:
    """Client for executing user-defined functions as LLM clients."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": False,
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
            from agent_actions.record.tracking import TrackedItem

            result: list[Any] = []
            for item in data:
                if isinstance(item, TrackedItem):
                    # Preserve TrackedItem type — provenance must survive stripping
                    stripped = strip(item)
                    result.append(TrackedItem(stripped, source_index=item._source_index))
                elif isinstance(item, dict):
                    result.append(strip(item))
                else:
                    result.append(item)
            return result

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
    def _with_short_names(data: Any, agent_config: dict[str, Any]) -> Any:
        """A record's *data* keyed by the short names of the ``as:`` include the action is in.

        ``data["write"]`` then holds the output of the same instance's ``write``. A key
        with no short name is kept; a list of records (FILE granularity) is left as it is.
        """
        origin = agent_config.get("_include")
        names = origin.get("names") if isinstance(origin, dict) else None
        if not names:
            return data
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return data
            if not isinstance(parsed, dict):
                return data
            return json.dumps(ToolClient._with_short_names(parsed, agent_config))
        if not isinstance(data, dict):
            return data
        renamed_finals = set(names.values())
        renamed = {key: value for key, value in data.items() if key not in renamed_finals}
        for short, final in names.items():
            if final in data:
                renamed[short] = data[final]
        return renamed

    @staticmethod
    def _stub(
        followed: "Scenario", agent_config: dict[str, Any], context_data: Any, udf_name: str
    ) -> Any:
        """What a tool the sandbox scenario stubs stores: the mock's record, not the UDF's.

        The UDF is not called. Its output schema checks the record as it checks the
        UDF's own output, so a value the schema refuses fails the record the same way.
        """
        # Imported here: the client registry loads this module in every run, and only a
        # sandbox run that stubs a tool builds a mock record.
        from agent_actions.llm.providers.agac.tool_stub import stub_output

        response = stub_output(followed, agent_config, context_data)
        errors = output_schema_errors(udf_name, response, agent_config["json_output_schema"])
        if errors:
            raise errors[0][1]
        return response

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
        builtin = builtin_tool(agent_config)
        if builtin is not None and builtin["tool"] == MCP and sandbox.is_active():
            # A sandbox run starts no outside server unless the scenario asks it to.
            followed = sandbox.scenario()
            name = str(agent_config.get("name"))
            if followed is not None and not followed.calls_for_real(name):
                return ToolClient._stub(followed, agent_config, context_data, name)
        if builtin is not None:
            data = ToolClient._strip_internal_fields(context_data)
            record = json.loads(data) if isinstance(data, str) else data
            return run_builtin(builtin, record, agent_config.get(RECORD_GUID_KEY))

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

        followed = sandbox.scenario()
        if followed is not None and followed.stubs(str(agent_config.get("name"))):
            return ToolClient._stub(followed, agent_config, context_data, model_name)

        # Strip internal metadata fields before passing to UDF
        clean_context = ToolClient._with_short_names(
            ToolClient._strip_internal_fields(context_data), agent_config
        )

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

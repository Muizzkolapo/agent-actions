"""Action-type processing functions extracted from ActionExpander."""

import logging
from typing import Any

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError, ConfigValidationError
from agent_actions.guards import GuardBehavior, GuardParser, parse_guard_config
from agent_actions.utils.constants import (
    DEFAULT_ACTION_KIND,
    HITL_OUTPUT_JSON_SCHEMA,
    HITL_OUTPUT_SCHEMA,
)

logger = logging.getLogger(__name__)


def process_guard_config(agent: dict[str, Any], action: dict[str, Any]) -> None:
    """Process guard configuration for an agent."""
    if not action.get("guard"):
        return

    guard_data = action["guard"]
    if isinstance(guard_data, str):
        guard_expr = GuardParser.parse(guard_data)
        if guard_expr.type.value == "udf":
            agent["conditional_clause"] = guard_expr.expression
        else:
            agent["guard"] = {"clause": guard_expr.expression, "scope": "item"}
    else:
        guard_config = parse_guard_config(guard_data)
        if guard_config.is_udf_condition():
            if guard_config.on_false == GuardBehavior.FILTER:
                action_name = action.get("name", "unknown")
                raise ConfigurationError(
                    "UDF conditions cannot use 'filter' behavior. "
                    "UDF conditions only support 'skip' behavior",
                    context={
                        "action_name": action_name,
                        "guard_behavior": "filter",
                        "operation": "expand_actions_to_agents",
                    },
                )
            agent["conditional_clause"] = guard_config.get_condition_expression()
        else:
            agent["guard"] = {
                "clause": guard_config.get_condition_expression(),
                "scope": "item",
                "behavior": guard_config.on_false.value,
            }


def process_tool_action(agent: dict[str, Any], action: dict[str, Any], run_mode: RunMode) -> None:
    """Process tool-specific action configuration."""
    action_kind = action.get("kind", DEFAULT_ACTION_KIND)
    if action_kind != "tool":
        return

    if not action.get("impl"):
        raise ConfigValidationError(
            "impl",
            "Tool actions must specify 'impl' field",
            context={
                "action": action.get("name", "unknown"),
                "kind": "tool",
                "hint": "Add 'impl: module.function_name' to your tool action",
            },
        )
    agent["model_vendor"] = "tool"
    agent["model_name"] = action.get("impl", action.get("name"))

    if run_mode == RunMode.BATCH:
        action_name = action.get("name", "unknown")
        raise ConfigurationError(
            "Tool actions do not support batch processing. "
            "Please set run_mode='online' or remove the run_mode "
            "setting to use the default",
            context={
                "action_name": action_name,
                "kind": "tool",
                "run_mode": "batch",
                "operation": "expand_actions_to_agents",
            },
        )

    # Tool actions MUST declare an output schema.
    # Ordering: runs BEFORE compile_output_schema (which populates
    # json_output_schema from schema:). Reads from the raw action dict.
    if not agent.get("json_output_schema") and not action.get("schema"):
        action_name = action.get("name", "unknown")
        raise ConfigValidationError(
            "schema",
            f"Tool action '{action_name}' has no output schema",
            context={
                "action": action_name,
                "kind": "tool",
                "hint": (
                    "Add schema: in YAML to declare the tool's output fields. "
                    "(output_type on @udf_tool was removed in this version)"
                ),
            },
        )


def process_hitl_action(
    agent: dict[str, Any], action: dict[str, Any], defaults: dict[str, Any]
) -> None:
    """Process HITL-specific action configuration.

    Validates the hitl config block, applies workflow-level timeout defaults,
    and injects the canonical HITL output schema.
    """
    hitl_config = action.get("hitl")
    if not hitl_config or not isinstance(hitl_config, dict):
        raise ConfigurationError(
            f"HITL action '{action.get('name', '?')}' requires a 'hitl' configuration block",
            context={"action": action.get("name")},
        )
    if not hitl_config.get("instructions"):
        raise ConfigurationError(
            f"HITL action '{action.get('name', '?')}' requires 'instructions' in hitl config",
            context={"action": action.get("name")},
        )
    agent["hitl"] = dict(hitl_config)
    # Apply workflow-level default timeout if action doesn't specify one
    hitl_timeout_default = defaults.get("hitl_timeout")
    if "timeout" not in hitl_config and hitl_timeout_default is not None:
        if (
            not isinstance(hitl_timeout_default, int)
            or isinstance(hitl_timeout_default, bool)
            or not (5 <= hitl_timeout_default <= 3600)
        ):
            raise ConfigurationError(
                f"defaults.hitl_timeout must be an integer between 5 and 3600, "
                f"got {hitl_timeout_default!r}",
                context={"hitl_timeout": hitl_timeout_default},
            )
        agent["hitl"]["timeout"] = hitl_timeout_default
    agent["output_schema"] = HITL_OUTPUT_SCHEMA
    agent["json_output_schema"] = HITL_OUTPUT_JSON_SCHEMA

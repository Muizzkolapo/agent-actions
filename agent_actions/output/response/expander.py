"""
Workflow format converter for expanding action-based configurations.

This module converts action-based workflow configurations into agent configurations,
handling loop expansion, template variables, and dependency mapping.

Implementation details are split across focused submodules:
- expander_validation: field and name validation
- expander_schema: schema processing and compilation
- expander_action_types: guard, tool, and HITL processing
- expander_merge: config merging and initialization
- expander_guard_validation: guard reference validation
"""

import logging
from typing import Any

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError
from agent_actions.utils.constants import DEFAULT_ACTION_KIND, HITL_FILE_GRANULARITY_ERROR

from .config_fields import get_default, inherit_simple_fields
from .expander_action_types import (
    process_guard_config,
    process_hitl_action,
    process_tool_action,
)
from .expander_guard_validation import (
    build_schema_registry,
    validate_agent_guards,
    validate_guard_references,
)
from .expander_merge import (
    deep_merge_context_scope,
    initialize_optional_fields,
    merge_directive_value,
    process_chunk_config,
)
from .expander_schema import (
    compile_output_schema,
    process_schema_config,
)
from .expander_validation import (
    validate_action_name,
    validate_required_fields,
    validate_vendor_exists,
)

logger = logging.getLogger(__name__)


class ActionExpander:
    """
    Converts action-based workflow configurations to agent configurations.

    Supports loop expansion for iterative action processing.
    """

    def __init__(self):
        """Initialize the ActionExpander."""
        # This class uses static methods for utility functions

    # ------------------------------------------------------------------
    # Backward-compatible delegates (thin wrappers, no logic)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_vendor_exists(vendor: str | None, action_name: str) -> None:
        return validate_vendor_exists(vendor, action_name)

    @staticmethod
    def _validate_action_name(action_name: str | None) -> None:
        return validate_action_name(action_name)

    @staticmethod
    def _validate_required_fields(agent: dict[str, Any], action_name: str) -> None:
        return validate_required_fields(agent, action_name)

    @staticmethod
    def _merge_directive_value(existing: Any, new_value: Any) -> Any:
        return merge_directive_value(existing, new_value)

    @staticmethod
    def _deep_merge_context_scope(
        defaults_scope: dict[str, Any] | None, action_scope: dict[str, Any] | None
    ) -> dict[str, Any]:
        return deep_merge_context_scope(defaults_scope, action_scope)

    @staticmethod
    def _process_schema_config(
        agent: dict[str, Any], action: dict[str, Any], template_replacer
    ) -> None:
        return process_schema_config(agent, action, template_replacer)

    @staticmethod
    def _process_guard_config(agent: dict[str, Any], action: dict[str, Any]) -> None:
        return process_guard_config(agent, action)

    @staticmethod
    def _process_tool_action(
        agent: dict[str, Any], action: dict[str, Any], run_mode: RunMode
    ) -> None:
        return process_tool_action(agent, action, run_mode)

    @staticmethod
    def _compile_output_schema(agent: dict[str, Any], action: dict[str, Any]) -> None:
        return compile_output_schema(agent, action)

    @staticmethod
    def _process_chunk_config(
        agent: dict[str, Any], action: dict[str, Any], defaults: dict[str, Any]
    ) -> None:
        return process_chunk_config(agent, action, defaults)

    @staticmethod
    def _initialize_optional_fields(agent: dict[str, Any]) -> None:
        return initialize_optional_fields(agent)

    @staticmethod
    def _build_schema_registry(agents: list[dict[str, Any]]) -> dict[str, Any]:
        return build_schema_registry(agents)

    @staticmethod
    def _validate_agent_guards(
        agent: dict[str, Any],
        validator,
        agent_indices: dict[str, int],
        action_schemas: dict[str, Any],
    ) -> list[str]:
        return validate_agent_guards(agent, validator, agent_indices, action_schemas)

    # ------------------------------------------------------------------
    # Orchestration methods (real logic stays here)
    # ------------------------------------------------------------------

    @staticmethod
    def _create_template_replacer(param_name: str, current_val, idx: int, values):
        """
        Create a template replacer function with captured loop variables.

        Args:
            param_name: Name of the loop parameter
            current_val: Current iteration value
            idx: Current index in the iteration
            values: List of all iteration values

        Returns:
            Template replacer function
        """

        def replacer(value):
            """Replace template variables in value."""
            if isinstance(value, str):
                result = value.replace(f"${{{param_name}}}", str(current_val))
                if idx > 0:
                    prev_value = values[idx - 1]
                    result = result.replace(f"${{{param_name}-1}}", str(prev_value))
                else:
                    result = result.replace(f"${{{param_name}-1}}", "")
                return result
            if isinstance(value, dict):
                return {
                    replacer(k) if isinstance(k, str) else k: replacer(v) for k, v in value.items()
                }
            if isinstance(value, list):
                return [replacer(item) for item in value]
            return value

        return replacer

    @staticmethod
    def _expand_versioned_action(
        action: dict[str, Any],
        version_config: dict[str, Any],
        defaults: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Expand a versioned action into multiple agent configurations.

        Args:
            action: Action configuration with versions
            version_config: Version configuration
            defaults: Default settings

        Returns:
            List of expanded agent configurations
        """
        agents: list[dict[str, Any]] = []
        param_name = version_config.get("param", "i")
        version_range = version_config.get("range", [1, 1])

        if len(version_range) == 2:
            start, end = version_range
            range_values = range(start, end + 1)
        else:
            range_values = version_range

        range_values_list = list(range_values)
        total_versions = len(range_values_list)

        for idx, i in enumerate(range_values_list):
            agent: dict[str, Any] = {}

            # Create template replacer with captured version variables
            template_replacer = ActionExpander._create_template_replacer(
                param_name, i, idx, range_values_list
            )

            agent["agent_type"] = f"{action.get('name', 'unknown')}_{i}"
            agent["name"] = f"{action.get('name')}_{i}"
            agent["is_versioned_agent"] = True
            agent["version_base_name"] = action.get("name", "unknown")
            agent["version_number"] = i
            agent["version_mode"] = version_config.get("mode", "parallel")

            # Compile version context for Jinja2 template rendering
            # This enables {{ i }}, {{ idx }}, {{ version.length }}, etc. in prompts
            version_context: dict[str, Any] = {
                "i": i,
                "idx": idx,
                "length": total_versions,
                "first": idx == 0,
                "last": idx == total_versions - 1,
            }
            # Add custom param name if different from default
            if param_name != "i":
                version_context[param_name] = i
            agent["_version_context"] = version_context

            # Create agent
            created_agent = ActionExpander._create_agent_from_action(
                action, defaults, agent, template_replacer
            )

            agents.append(created_agent)

        return agents

    @staticmethod
    def _create_agent_from_action(
        action: dict[str, Any],
        defaults: dict[str, Any],
        agent: dict[str, Any],
        template_replacer,
    ) -> dict[str, Any]:
        """
        Create an agent configuration from an action.

        Args:
            action: Action configuration from new format
            defaults: Default settings
            agent: Pre-initialized agent dict with agent_type and name already set
            template_replacer: Function to replace template variables

        Returns:
            Completed agent configuration
        """
        # Inherit simple fields (includes is_operational from config)
        inherit_simple_fields(agent, action, defaults)

        action_kind = action.get("kind", DEFAULT_ACTION_KIND)
        # HITL is a non-LLM action type and should always route to the HITL client,
        # regardless of inherited/default model_vendor.
        if action_kind == "hitl":
            agent["model_vendor"] = "hitl"

        # Tool and HITL actions must always run online — they cannot be batched.
        # Only inherit run_mode from defaults for LLM actions; for tool/hitl, fall
        # back to the hardcoded default (online) unless the action explicitly overrides.
        if action_kind in {"tool", "hitl"} and action.get("run_mode") is None:
            agent["run_mode"] = get_default("run_mode")

        # Validate configuration
        validate_vendor_exists(agent["model_vendor"], action.get("name", "unknown"))
        if action_kind not in {"tool", "hitl"}:
            validate_required_fields(agent, action.get("name", "unknown"))

        # Process schema configuration
        process_schema_config(agent, action, template_replacer)

        # Process guard configuration
        process_guard_config(agent, action)

        # Process prompt
        prompt = action.get("prompt")
        agent["prompt"] = template_replacer(prompt) if prompt else None

        # Process tool actions
        run_mode = agent["run_mode"]
        process_tool_action(agent, action, run_mode)
        if action_kind == "hitl":
            process_hitl_action(agent, action, defaults)

        # Compile YAML schema: to json_output_schema (all action types).
        # NOTE: Must run AFTER HITL schema injection above — compile_output_schema
        # skips when json_output_schema is already set, preserving the canonical HITL schema.
        compile_output_schema(agent, action)

        # Process granularity
        # HITL reviews should see the full dataset in one step, so default to FILE.
        if action_kind == "hitl":
            granularity = action.get("granularity", "file")
            if granularity.lower() == "record":
                raise ConfigurationError(
                    HITL_FILE_GRANULARITY_ERROR,
                    context={"agent_name": action.get("name", "?")},
                )
        else:
            granularity = action.get(
                "granularity", defaults.get("granularity", get_default("granularity"))
            )
        if granularity:
            agent["granularity"] = (
                granularity.capitalize() if isinstance(granularity, str) else granularity
            )

        # Handle context_scope (complex field - not in SIMPLE_CONFIG_FIELDS)
        # Deep merge: action directives merge with defaults (not replace)
        context_scope_defaults = defaults.get("context_scope")
        context_scope_action = action.get("context_scope")
        if context_scope_defaults or context_scope_action:
            agent["context_scope"] = deep_merge_context_scope(
                context_scope_defaults, context_scope_action
            )

        # Initialize dependencies from action if present, else empty list
        agent["dependencies"] = action.get("dependencies", [])

        # Process chunk configuration
        process_chunk_config(agent, action, defaults)

        # Initialize optional fields
        initialize_optional_fields(agent)

        # Process version consumption
        version_consumption = action.get("version_consumption")
        if version_consumption:
            agent["version_consumption_config"] = {
                "source": version_consumption.get("source"),
                "pattern": version_consumption.get("pattern", "merge"),
            }
        else:
            agent["version_consumption_config"] = None

        # Process interceptors
        interceptors = action.get("interceptors")
        if interceptors:
            agent["interceptors"] = interceptors

        return agent

    @staticmethod
    def expand_actions_to_agents(action_config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """
        Convert action-based configuration to agent-based configuration with loop expansion.

        If actions were already expanded by the render/compile step (indicated by
        _version_context being present), this function skips re-expansion.

        Args:
            action_config: Configuration with actions that may contain loops

        Returns:
            Expanded agent configuration ready for execution (ActionConfigMap)
        """
        workflow_name = action_config.get("name", "workflow")
        actions = action_config.get("actions", [])
        defaults = action_config.get("defaults", {})

        # We no longer process 'plan' for dependencies.
        # Dependencies must be explicitly defined in the action config.

        agents: list[dict[str, Any]] = []
        for action in actions:
            validate_action_name(action.get("name"))

            # Check if this action was already expanded by render step
            # Pre-expanded actions have _version_context set
            is_pre_expanded = "_version_context" in action

            version_config = action.get("versions")
            if version_config and not is_pre_expanded:
                # Expand versioned action into multiple agents (legacy path)
                version_agents = ActionExpander._expand_versioned_action(
                    action, version_config, defaults
                )
                agents.extend(version_agents)
            else:
                # Either non-versioned action OR pre-expanded versioned action
                agent: dict[str, Any] = {}
                agent["agent_type"] = action.get("name", "unknown")
                agent["name"] = action.get("name")

                # Preserve version context from render step if present
                if is_pre_expanded:
                    version_ctx = action["_version_context"]
                    agent["is_versioned_agent"] = True
                    agent["version_base_name"] = version_ctx.get("base_name", action.get("name"))
                    agent["version_number"] = version_ctx.get("i")
                    agent["version_mode"] = action.get("version_mode", "parallel")
                    agent["_version_context"] = version_ctx

                # Check for explicit dependencies in action, defaulting to empty list
                # This is handled inside _create_agent_from_action via inheritance,
                # but we ensure it persists
                created_agent = ActionExpander._create_agent_from_action(
                    action, defaults, agent, lambda x: x
                )
                if "dependencies" not in created_agent and "dependencies" in action:
                    created_agent["dependencies"] = action["dependencies"]

                agents.append(created_agent)

        return {workflow_name: agents}

    @staticmethod
    def validate_guard_references(agents: list[dict[str, Any]], strict: bool = True) -> list[str]:
        return validate_guard_references(agents, strict)


__all__ = ["ActionExpander"]

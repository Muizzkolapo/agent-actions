"""
Workflow format converter for expanding action-based configurations.

This module converts action-based workflow configurations into agent configurations,
handling loop expansion, template variables, and dependency mapping.
"""

import logging
from typing import Dict, Any, Optional

from agent_actions.errors import ConfigValidationError, ConfigurationError
from agent_actions.llm.config.vendor_config import VendorType
from agent_actions.output.response.guard_parser import GuardParser
from agent_actions.output.response.consolidated_guard import GuardBehavior, parse_guard_config
from agent_actions.output.response.schema import compile_unified_schema
from agent_actions.utils.constants import RESERVED_AGENT_NAMES
from agent_actions.utils.udf_management import get_udf_metadata
from agent_actions.input.preprocessing.field_resolution import ReferenceValidator, ReferenceParser
from .config_types import AgentConfigMap, AgentEntryDict, AgentConfigList
from .config_field_definitions import inherit_simple_fields

logger = logging.getLogger(__name__)


class ActionExpander:
    """
    Converts action-based workflow configurations to agent configurations.

    Supports loop expansion for iterative action processing.
    """

    def __init__(self):
        """Initialize the ActionExpander."""
        # This class uses static methods for utility functions

    @staticmethod
    def _validate_vendor_exists(vendor: Optional[str], action_name: str) -> None:
        """
        Validate vendor is a known/supported vendor.

        Args:
            vendor: Vendor name to validate
            action_name: Name of action for error context

        Raises:
            ConfigValidationError: If vendor is unknown
        """
        if not vendor:
            return
        valid_vendors = [v.value for v in VendorType]
        if vendor not in valid_vendors:
            raise ConfigValidationError(
                "model_vendor",
                f"Unknown vendor '{vendor}'",
                context={
                    "action": action_name,
                    "vendor": vendor,
                    "supported_vendors": valid_vendors,
                    "hint": f"Valid vendors: {', '.join(valid_vendors)}",
                },
            )

    @staticmethod
    def _validate_action_name(action_name: Optional[str]) -> None:
        """Validate action name is not reserved."""
        if not action_name or not isinstance(action_name, str):
            raise ConfigValidationError(
                "name",
                "Action name must be a non-empty string",
                context={"action_name": action_name, "operation": "expand_actions_to_agents"},
            )

        normalized = action_name.strip().lower()
        if normalized in RESERVED_AGENT_NAMES:
            raise ConfigValidationError(
                "name",
                f"Reserved action name '{action_name}' cannot be used",
                context={
                    "action_name": action_name,
                    "reserved_names": sorted(RESERVED_AGENT_NAMES),
                    "operation": "expand_actions_to_agents",
                    "hint": "Rename the action to avoid reserved namespaces.",
                },
            )

    @staticmethod
    def _validate_required_fields(agent: AgentEntryDict, action_name: str) -> None:
        """
        Validate that required configuration fields are present after hierarchy resolution.

        This validation ensures that essential fields (vendor, model, api_key) are defined
        at least once across the 3-level hierarchy (project → workflow → action).

        Args:
            agent: Agent configuration dict after hierarchy resolution
            action_name: Name of the action being validated (for error messages)

        Raises:
            ConfigValidationError: If any required field is missing
        """
        required_fields = {
            "model_vendor": agent.get("model_vendor"),
            "model_name": agent.get("model_name"),
            "api_key": agent.get("api_key"),
        }
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            field_display_names = {
                "model_vendor": "vendor/model_vendor",
                "model_name": "model/model_name",
                "api_key": "api_key",
            }
            missing_display = [field_display_names.get(f, f) for f in missing_fields]
            raise ConfigValidationError(
                config_key=", ".join(missing_fields),
                reason="Required configuration fields are missing after hierarchy resolution",
                context={
                    "action_name": action_name,
                    "missing_fields": missing_fields,
                    "missing_display": missing_display,
                    "operation": "expand_actions_to_agents",
                    "hint": (
                        "Add missing fields to agent_actions.yml (project-level), "
                        "workflow defaults, or action config"
                    ),
                },
            )

    @staticmethod
    def _merge_directive_value(existing: Any, new_value: Any) -> Any:
        """Merge two directive values based on their types."""
        if isinstance(existing, dict) and isinstance(new_value, dict):
            return {**existing, **new_value}
        if isinstance(existing, list) and isinstance(new_value, list):
            return list(dict.fromkeys(existing + new_value))
        return new_value

    @staticmethod
    def _deep_merge_context_scope(
        defaults_scope: Optional[Dict[str, Any]], action_scope: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Deep merge context_scope directives from defaults and action levels.

        Action-level directives are merged with (not replace) defaults directives.
        This allows actions to define drop/observe while inheriting seed_data from defaults.
        """
        if not defaults_scope:
            return action_scope or {}
        if not action_scope:
            return defaults_scope or {}

        merged = {**defaults_scope}

        for key, value in action_scope.items():
            if key in merged:
                merged[key] = ActionExpander._merge_directive_value(merged[key], value)
            else:
                merged[key] = value

        return merged

    @staticmethod
    def _process_schema_config(
        agent: AgentEntryDict, action: Dict[str, Any], template_replacer
    ) -> None:
        """Process schema configuration for an agent."""
        schema_value = action.get("schema") or action.get("output_schema")
        if schema_value:
            schema_value = template_replacer(schema_value)
            if isinstance(schema_value, str):
                agent["schema_name"] = schema_value
            elif isinstance(schema_value, dict):
                agent["schema"] = schema_value
            else:
                agent["schema"] = schema_value

    @staticmethod
    def _process_guard_config(agent: AgentEntryDict, action: Dict[str, Any]) -> None:
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

    @staticmethod
    def _process_tool_action(agent: AgentEntryDict, action: Dict[str, Any], run_mode: str) -> None:
        """Process tool-specific action configuration."""
        action_kind = action.get("kind", "llm")
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

        # Add UDF output schema to agent config (REQUIRED for schema validation)
        impl_name = action.get("impl")
        if impl_name:
            try:
                udf_metadata = get_udf_metadata(impl_name)

                # BREAKING: output_type is now effectively required for type safety
                # UDFs without output_type will pass here but fail during field validation
                if udf_metadata.get("json_output_schema"):
                    agent["output_schema"] = udf_metadata["output_schema"]
                    agent["json_output_schema"] = udf_metadata["json_output_schema"]
            except (ValueError, KeyError, ImportError):
                # UDF not found or not yet registered - continue without schema
                # Schema validation will fail later if fields are referenced
                pass

        if run_mode == "batch" and action.get("run_mode") == "batch":
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
        if run_mode == "batch":
            agent["run_mode"] = "online"

    @staticmethod
    def _add_llm_output_schema(agent: AgentEntryDict, action: Dict[str, Any]) -> None:
        """Add output schema to agent config for LLM actions with schemas.

        This enables guard field reference validation against LLM output schemas,
        providing the same compile-time validation that UDFs receive.
        """
        # Skip tool actions (handled by _process_tool_action)
        if action.get("kind") == "tool" or agent.get("model_vendor") == "tool":
            return

        # Skip if already has json_output_schema
        if agent.get("json_output_schema"):
            return

        # Get schema from action (already processed by _process_schema_config)
        schema_fields = agent.get("schema")
        if not schema_fields:
            return

        # Build unified schema format
        agent_name = agent.get("agent_type", "unknown")

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
            return

        # Compile to JSON Schema for validation
        try:
            # Use 'openai' format as canonical JSON Schema
            compiled = compile_unified_schema(unified_schema, "openai")
            agent["output_schema"] = unified_schema
            agent["json_output_schema"] = compiled.get("schema", compiled)
        except (ValueError, KeyError, TypeError):
            # Schema compilation failed - skip validation for this action
            pass

    @staticmethod
    def _process_chunk_config(
        agent: AgentEntryDict, action: Dict[str, Any], defaults: Dict[str, Any]
    ) -> None:
        """Process chunk configuration for an agent."""
        chunk_config = action.get("chunk_config", defaults.get("chunk_config", {}))
        if chunk_config:
            agent["chunk_config"] = chunk_config
        else:
            agent["chunk_config"] = {}
            if action.get("chunk_size") or defaults.get("chunk_size"):
                agent["chunk_config"]["chunk_size"] = action.get(
                    "chunk_size", defaults.get("chunk_size", 300)
                )
            if action.get("chunk_overlap") or defaults.get("chunk_overlap"):
                agent["chunk_config"]["chunk_overlap"] = action.get(
                    "chunk_overlap", defaults.get("chunk_overlap", 10)
                )

    @staticmethod
    def _initialize_optional_fields(agent: AgentEntryDict) -> None:
        """Initialize optional fields in agent configuration."""
        agent["skip_if"] = None
        agent["ephemeral"] = None
        agent["add_dispatch"] = None
        agent["anthropic_version"] = None
        agent["enable_prompt_caching"] = None
        if "conditional_clause" not in agent:
            agent["conditional_clause"] = None
        if "guard" not in agent:
            agent["guard"] = None

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
        action: Dict[str, Any],
        version_config: Dict[str, Any],
        defaults: Dict[str, Any],
        is_operational: bool,
    ) -> AgentConfigList:
        """
        Expand a versioned action into multiple agent configurations.

        Args:
            action: Action configuration with versions
            version_config: Version configuration
            defaults: Default settings
            is_operational: Whether this action should run

        Returns:
            List of expanded agent configurations
        """
        agents: AgentConfigList = []
        param_name = version_config.get("param", "i")
        version_range = version_config.get("range", [1, 1])

        if len(version_range) == 2:
            start, end = version_range
            range_values = range(start, end + 1)
        else:
            range_values = version_range

        range_values_list = list(range_values)
        for idx, i in enumerate(range_values_list):
            agent: AgentEntryDict = {}

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

            # Create agent
            created_agent = ActionExpander._create_agent_from_action(
                action, defaults, agent, template_replacer, is_operational=is_operational
            )

            agents.append(created_agent)

        return agents

    @staticmethod
    def _create_agent_from_action(
        action: Dict[str, Any],
        defaults: Dict[str, Any],
        agent: AgentEntryDict,
        template_replacer,
        is_operational: bool = True,
    ) -> AgentEntryDict:
        """
        Create an agent configuration from an action.

        Args:
            action: Action configuration from new format
            defaults: Default settings
            agent: Pre-initialized agent dict with agent_type and name already set
            template_replacer: Function to replace template variables
            is_operational: Whether this action should run (based on plan)

        Returns:
            Completed agent configuration
        """
        # Inherit simple fields and set operational status
        inherit_simple_fields(agent, action, defaults)
        agent["is_operational"] = is_operational

        # Validate configuration
        ActionExpander._validate_vendor_exists(agent["model_vendor"], action.get("name", "unknown"))
        action_kind = action.get("kind", "llm")
        if action_kind != "tool":
            ActionExpander._validate_required_fields(agent, action.get("name", "unknown"))

        # Process schema configuration
        ActionExpander._process_schema_config(agent, action, template_replacer)

        # Process guard configuration
        ActionExpander._process_guard_config(agent, action)

        # Process prompt
        prompt = action.get("prompt")
        agent["prompt"] = template_replacer(prompt) if prompt else None

        # Process tool actions
        run_mode = agent["run_mode"]
        ActionExpander._process_tool_action(agent, action, run_mode)

        # Add output schema for LLM actions (enables guard field validation)
        ActionExpander._add_llm_output_schema(agent, action)

        # Process granularity
        granularity = action.get("granularity", defaults.get("granularity", "record"))
        if granularity:
            agent["granularity"] = (
                granularity.capitalize() if isinstance(granularity, str) else granularity
            )

        # Handle context_scope (complex field - not in SIMPLE_CONFIG_FIELDS)
        # Deep merge: action directives merge with defaults (not replace)
        context_scope_defaults = defaults.get("context_scope")
        context_scope_action = action.get("context_scope")
        if context_scope_defaults or context_scope_action:
            agent["context_scope"] = ActionExpander._deep_merge_context_scope(
                context_scope_defaults, context_scope_action
            )

        # Initialize dependencies from action if present, else empty list
        agent["dependencies"] = action.get("dependencies", [])

        # Process chunk configuration
        ActionExpander._process_chunk_config(agent, action, defaults)

        # Initialize optional fields
        ActionExpander._initialize_optional_fields(agent)

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
    def expand_actions_to_agents(action_config: Dict[str, Any]) -> AgentConfigMap:
        """
        Convert action-based configuration to agent-based configuration with loop expansion.

        Args:
            action_config: Configuration with actions that may contain loops

        Returns:
            Expanded agent configuration ready for execution (AgentConfigMap)
        """
        workflow_name = action_config.get("name", "workflow")
        actions = action_config.get("actions", [])
        defaults = action_config.get("defaults", {})

        # We no longer process 'plan' for dependencies.
        # Dependencies must be explicitly defined in the action config.

        agents: AgentConfigList = []
        for action in actions:
            ActionExpander._validate_action_name(action.get("name"))
            # Assuming all actions listed are operational unless specified otherwise,
            # or we could filter by some other logic. For now, we take all actions.
            is_operational = True

            version_config = action.get("versions")
            if version_config:
                # Expand versioned action into multiple agents
                version_agents = ActionExpander._expand_versioned_action(
                    action, version_config, defaults, is_operational
                )
                agents.extend(version_agents)
            else:
                agent: AgentEntryDict = {}
                agent["agent_type"] = action.get("name", "unknown")
                agent["name"] = action.get("name")

                # Check for explicit dependencies in action, defaulting to empty list
                # This is handled inside _create_agent_from_action via inheritance,
                # but we ensure it persists
                created_agent = ActionExpander._create_agent_from_action(
                    action, defaults, agent, lambda x: x, is_operational=is_operational
                )
                if "dependencies" not in created_agent and "dependencies" in action:
                    created_agent["dependencies"] = action["dependencies"]

                agents.append(created_agent)

        return {workflow_name: agents}

    @staticmethod
    def _build_schema_registry(agents: AgentConfigList) -> Dict[str, Any]:
        """
        Build schema registry from agent configs.

        Args:
            agents: List of agent configurations

        Returns:
            Dictionary mapping agent names to their JSON output schemas
        """
        action_schemas = {}
        for agent in agents:
            agent_name = agent.get("agent_type") or agent.get("name", "unknown")

            # Add schema if present (both LLM and UDF actions can have schemas)
            if agent.get("json_output_schema"):
                action_schemas[agent_name] = agent["json_output_schema"]

        return action_schemas

    @staticmethod
    def _validate_agent_guards(
        agent: AgentEntryDict,
        validator: ReferenceValidator,
        agent_indices: Dict[str, int],
        action_schemas: Dict[str, Any],
    ) -> list[str]:
        """
        Validate guard references for a single agent.

        Args:
            agent: Agent configuration
            validator: Reference validator instance
            agent_indices: Mapping of agent names to indices
            action_schemas: Mapping of agent names to schemas

        Returns:
            List of error messages
        """
        errors = []
        agent_name = agent.get("agent_type") or agent.get("name", "unknown")

        # Check guard conditions
        guard = agent.get("guard")
        if guard and isinstance(guard, dict):
            clause = guard.get("clause", "")
            if clause:
                parser = ReferenceParser()
                references = parser.parse_batch(clause)

                guard_errors = validator.validate_with_schemas(
                    references=references,
                    agent_config=agent,
                    agent_indices=agent_indices,
                    action_schemas=action_schemas,
                    current_agent_name=agent_name,
                )
                errors.extend(guard_errors)

        # Check conditional_clause (UDF guards)
        conditional_clause = agent.get("conditional_clause")
        if conditional_clause and isinstance(conditional_clause, str):
            parser = ReferenceParser()
            references = parser.parse_batch(conditional_clause)

            guard_errors = validator.validate_with_schemas(
                references=references,
                agent_config=agent,
                agent_indices=agent_indices,
                action_schemas=action_schemas,
                current_agent_name=agent_name,
            )
            errors.extend(guard_errors)

        return errors

    @staticmethod
    def validate_guard_references(agents: AgentConfigList, strict: bool = True) -> list[str]:
        """
        Validate that guard conditions only reference valid upstream actions.

        This should be called after expand_actions_to_agents() to ensure all
        guard field references (e.g., "extract_facts.count > 5") reference
        actions that exist and are upstream in the dependency graph.

        Args:
            agents: List of agent configurations from expand_actions_to_agents()
            strict: If True, raise exception on validation errors. If False,
                   return list of error messages.

        Returns:
            List of error messages (empty if all valid)

        Raises:
            ConfigValidationError: If strict=True and validation fails

        Example:
            config = {'name': 'my_workflow', 'actions': [...]}
            result = ActionExpander.expand_actions_to_agents(config)
            agents = result['my_workflow']

            # Validate guard references
            errors = ActionExpander.validate_guard_references(agents, strict=False)
            if errors:
                for error in errors:
                    logger.warning(error)
        """
        errors = []
        validator = ReferenceValidator(strict_dependencies=True)

        # Build agent_indices from the list
        agent_indices = {}
        for idx, agent in enumerate(agents):
            agent_name = agent.get("agent_type") or agent.get("name", f"unknown_{idx}")
            agent_indices[agent_name] = idx

        # Build schema registry from agent configs
        action_schemas = ActionExpander._build_schema_registry(agents)

        # Validate each agent's guard references with schemas
        for agent in agents:
            agent_errors = ActionExpander._validate_agent_guards(
                agent, validator, agent_indices, action_schemas
            )
            errors.extend(agent_errors)

        # Handle strict mode
        if strict and errors:
            raise ConfigValidationError(
                config_key="guard",
                reason="Guard references invalid actions",
                context={
                    "errors": errors,
                    "hint": (
                        "Ensure guard conditions only reference actions that are "
                        "declared in the dependencies list and exist in the workflow."
                    ),
                },
            )

        return errors


__all__ = ["ActionExpander"]

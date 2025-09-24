"""
Format converter for handling both old and new workflow formats.

This module provides detection and conversion between:
- Old format: {"workflow-name": [agent1, agent2, ...]}
- New format: {"name": "workflow-name", "actions": [action1, action2, ...]}
"""

from typing import Dict, Any, List, Optional, Union
from .config_types import AgentConfigMap, AgentEntryDict, AgentConfigList
import logging

logger = logging.getLogger(__name__)


class WorkflowFormatConverter:
    """Handles detection and conversion between old and new workflow formats."""

    @staticmethod
    def detect_format(config: Dict[str, Any]) -> str:
        """
        Detect whether a config uses old or new format.

        Args:
            config: Loaded YAML configuration

        Returns:
            "old" or "new"
        """
        # New format indicators
        if 'name' in config and 'actions' in config:
            return "new"

        # Old format indicators - top level keys should be workflow names
        # and values should be lists of dicts with agent_type
        for key, value in config.items():
            if isinstance(value, list) and value:
                first_item = value[0]
                if isinstance(first_item, dict) and 'agent_type' in first_item:
                    return "old"

        # Default to old for backwards compatibility
        return "old"

    @staticmethod
    def _create_agent_from_action(action: Dict[str, Any], defaults: Dict[str, Any], agent: AgentEntryDict, template_replacer, is_operational: bool = True) -> AgentEntryDict:
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
        # Model configuration
        agent['model_vendor'] = action.get('vendor', defaults.get('vendor'))
        agent['model_name'] = action.get('model', defaults.get('model'))

        # Execution settings
        agent['is_operational'] = is_operational
        agent['run_mode'] = defaults.get('run_mode', 'online')
        agent['use_few_shot_samples'] = action.get('few_shot', 0)

        # Schema handling - apply template replacement
        schema_value = action.get('schema') or action.get('output_schema')
        if schema_value:
            schema_value = template_replacer(schema_value)
            if isinstance(schema_value, str):
                agent['schema_name'] = schema_value
            elif isinstance(schema_value, dict):
                agent['schema'] = schema_value
            else:
                agent['schema'] = schema_value

        # Conditional logic - handle both consolidated and legacy guard formats
        if action.get('guard'):
            from agent_actions.core.utils.guard_parser import GuardParser
            from agent_actions.core.utils.consolidated_guard import GuardBehavior, parse_guard_config

            guard_data = action['guard']

            # Handle both legacy string format and new consolidated format
            if isinstance(guard_data, str):
                # Legacy format - parse using existing logic
                guard_expr = GuardParser.parse(guard_data)

                if guard_expr.type.value == 'udf':
                    # UDF guard - use legacy conditional_clause for execution
                    agent['conditional_clause'] = guard_expr.expression
                else:
                    # SQL guard - use where_clause
                    agent['where_clause'] = {
                        'clause': guard_expr.expression,
                        'scope': 'item'
                    }
            else:
                # New consolidated format
                guard_config = parse_guard_config(guard_data)

                if guard_config.is_udf_condition():
                    # UDF conditions use conditional_clause (legacy support for skip behavior only)
                    if guard_config.on_false == GuardBehavior.FILTER:
                        raise ValueError("UDF conditions cannot use 'filter' behavior. UDF conditions only support 'skip' behavior.")
                    agent['conditional_clause'] = guard_config.get_condition_expression()
                else:
                    # SQL conditions use where_clause with behavior specification
                    agent['where_clause'] = {
                        'clause': guard_config.get_condition_expression(),
                        'scope': 'item',
                        'behavior': guard_config.on_false.value  # 'filter' or 'skip'
                    }
                # Future: Add support for WRITE_TO, REPROCESS behaviors

        # Prompt
        agent['prompt'] = action.get('prompt')

        # Handle tool vs LLM actions
        action_kind = action.get('kind', 'llm')
        if action_kind == 'tool':
            agent['model_vendor'] = 'tool'
            agent['model_name'] = action.get('impl', action.get('name'))

        # Granularity
        granularity = action.get('granularity', defaults.get('granularity'))
        if granularity:
            agent['granularity'] = granularity.capitalize() if isinstance(granularity, str) else granularity

        # Data flow collections - apply template replacement
        current_granularity = agent.get('granularity', 'Record')
        is_file_level = current_granularity == 'File'
        is_tool_action = action_kind == 'tool'

        if not (is_file_level and is_tool_action):
            # Apply template replacement to collection fields
            observe = template_replacer(action.get('observe', []))
            drops = template_replacer(action.get('drops', []))
            writes = template_replacer(action.get('writes', []))
            reads = template_replacer(action.get('reads', []))

            agent['side_collection'] = observe if isinstance(observe, list) else [observe]
            agent['remove_collection'] = drops if isinstance(drops, list) else [drops]

        # Dependencies - will be populated from plan
        agent['dependencies'] = []
        agent['parent'] = []

        # Default empty collections
        agent['chunk_config'] = {}
        agent['skip_if'] = None
        agent['ephemeral'] = None
        agent['add_dispatch'] = None
        agent['anthropic_version'] = None
        agent['enable_prompt_caching'] = None

        # Initialize conditional fields if not already set
        if 'conditional_clause' not in agent:
            agent['conditional_clause'] = None
        if 'where_clause' not in agent:
            agent['where_clause'] = None

        return agent

    @staticmethod
    def convert_new_to_old(new_config: Dict[str, Any]) -> AgentConfigMap:
        """
        Convert new format to old format for execution.

        Args:
            new_config: New format configuration

        Returns:
            Old format configuration (AgentConfigMap)
        """
        workflow_name = new_config.get('name', 'workflow')
        actions = new_config.get('actions', [])
        defaults = new_config.get('defaults', {})

        # Extract actions that are in the plan
        plan = new_config.get('plan', [])
        actions_in_plan = set()
        for plan_item in plan:
            if '<-' in plan_item:
                action_name = plan_item.split('<-')[0].strip()
            else:
                action_name = plan_item.strip()
            actions_in_plan.add(action_name)

        # Convert actions to agents
        agents: AgentConfigList = []

        for action in actions:
            # Check if this action is in the plan
            action_name = action.get('name')
            is_in_plan = action_name in actions_in_plan

            # Check if this action has a loop configuration
            loop_config = action.get('loop')
            if loop_config:
                # Expand loop into multiple agent instances
                param_name = loop_config.get('param', 'i')
                loop_range = loop_config.get('range', [1, 1])

                # Generate range values
                if len(loop_range) == 2:
                    start, end = loop_range
                    range_values = range(start, end + 1)
                else:
                    range_values = loop_range

                # Create an agent for each loop iteration
                for i in range_values:
                    agent: AgentEntryDict = {}

                    # Replace template variables in relevant fields
                    def replace_template_var(value):
                        if isinstance(value, str):
                            return value.replace(f'${{{param_name}}}', str(i))
                        elif isinstance(value, dict):
                            # Replace in both keys and values
                            return {
                                replace_template_var(k) if isinstance(k, str) else k: replace_template_var(v)
                                for k, v in value.items()
                            }
                        elif isinstance(value, list):
                            return [replace_template_var(item) for item in value]
                        return value

                    # Core fields
                    agent['agent_type'] = f"{action.get('name', 'unknown')}_{i}"
                    agent['name'] = f"{action.get('name')}_{i}"

                    # Continue with rest of agent setup
                    agents.append(WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, replace_template_var, is_operational=is_in_plan))
            else:
                # No loop - create single agent
                agent: AgentEntryDict = {}

                # Core fields
                agent['agent_type'] = action.get('name', 'unknown')
                agent['name'] = action.get('name')

                agents.append(WorkflowFormatConverter._create_agent_from_action(action, defaults, agent, lambda x: x, is_operational=is_in_plan))

        # Extract dependencies from plan
        plan = new_config.get('plan', [])

        # Create mapping of action names to agent indices (accounting for loops)
        agent_name_to_indices = {}
        agent_index = 0
        for action in actions:
            action_name = action.get('name')
            loop_config = action.get('loop')

            if loop_config:
                # For looped actions, map to multiple indices
                loop_range = loop_config.get('range', [1, 1])
                if len(loop_range) == 2:
                    start, end = loop_range
                    num_iterations = end - start + 1
                else:
                    num_iterations = len(loop_range)

                agent_name_to_indices[action_name] = list(range(agent_index, agent_index + num_iterations))
                agent_index += num_iterations
            else:
                agent_name_to_indices[action_name] = [agent_index]
                agent_index += 1

        for plan_item in plan:
            if '<-' in plan_item:
                action_name, deps_str = plan_item.split('<-', 1)
                action_name = action_name.strip()
                deps = [dep.strip() for dep in deps_str.split(',')]

                # Find the corresponding agent(s) and set dependencies
                if action_name in agent_name_to_indices:
                    for agent_idx in agent_name_to_indices[action_name]:
                        # For looped actions, dependencies should reference the expanded names
                        expanded_deps = []
                        for dep in deps:
                            if dep in agent_name_to_indices:
                                # If dependency is also looped, use all expanded names
                                for dep_idx in agent_name_to_indices[dep]:
                                    expanded_deps.append(agents[dep_idx]['agent_type'])
                            else:
                                expanded_deps.append(dep)
                        agents[agent_idx]['dependencies'] = expanded_deps

        return {workflow_name: agents}

    @staticmethod
    def ensure_old_format(config: Dict[str, Any]) -> AgentConfigMap:
        """
        Ensure config is in old format, converting if necessary.

        Args:
            config: Configuration in either format

        Returns:
            Configuration in old format
        """
        format_type = WorkflowFormatConverter.detect_format(config)

        if format_type == "new":
            logger.info("Detected new workflow format, converting to old format for execution")
            return WorkflowFormatConverter.convert_new_to_old(config)
        else:
            logger.debug("Using existing old format configuration")
            return config  # Already in old format


__all__ = ["WorkflowFormatConverter"]
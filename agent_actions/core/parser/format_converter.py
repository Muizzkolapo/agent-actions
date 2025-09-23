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

        # Convert actions to agents
        agents: AgentConfigList = []

        for action in actions:
            agent: AgentEntryDict = {}

            # Core fields
            agent['agent_type'] = action.get('name', 'unknown')
            agent['name'] = action.get('name')

            # Model configuration
            agent['model_vendor'] = action.get('vendor', defaults.get('vendor'))
            agent['model_name'] = action.get('model', defaults.get('model'))

            # Execution settings
            agent['is_operational'] = True
            agent['run_mode'] = defaults.get('run_mode', 'online')
            agent['use_few_shot_samples'] = action.get('few_shot', 0)

            # Data flow - convert new format back to old
            agent['side_collection'] = action.get('observe', [])
            agent['remove_collection'] = action.get('drops', [])

            # Schema handling - check both 'schema' and 'output_schema' fields
            schema_value = action.get('schema') or action.get('output_schema')
            if schema_value:
                if isinstance(schema_value, str):
                    agent['schema_name'] = schema_value
                else:
                    agent['schema'] = schema_value

            # Conditional logic
            if action.get('guard'):
                agent['where_clause'] = {
                    'clause': action['guard'],
                    'scope': 'item'
                }

            # Prompt
            agent['prompt'] = action.get('prompt')

            # Handle tool vs LLM actions
            action_kind = action.get('kind', 'llm')
            if action_kind == 'tool':
                # For tool actions, model_vendor should be 'tool' and model_name contains the implementation path
                agent['model_vendor'] = 'tool'
                agent['model_name'] = action.get('impl', action.get('name'))  # Use impl or fallback to action name

            # Granularity
            granularity = action.get('granularity', defaults.get('granularity'))
            if granularity:
                agent['granularity'] = granularity.capitalize() if isinstance(granularity, str) else granularity

            # Dependencies - need to extract from plan
            agent['dependencies'] = []  # Will be populated from plan
            agent['parent'] = []

            # Default empty collections
            agent['chunk_config'] = {}
            agent['conditional_clause'] = None
            agent['skip_if'] = None
            agent['ephemeral'] = None
            agent['add_dispatch'] = None
            agent['anthropic_version'] = None
            agent['enable_prompt_caching'] = None

            agents.append(agent)

        # Extract dependencies from plan
        plan = new_config.get('plan', [])
        action_name_to_index = {action.get('name'): i for i, action in enumerate(actions)}

        for plan_item in plan:
            if '<-' in plan_item:
                action_name, deps_str = plan_item.split('<-', 1)
                action_name = action_name.strip()
                deps = [dep.strip() for dep in deps_str.split(',')]

                # Find the corresponding agent and set dependencies
                if action_name in action_name_to_index:
                    agent_index = action_name_to_index[action_name]
                    agents[agent_index]['dependencies'] = deps

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
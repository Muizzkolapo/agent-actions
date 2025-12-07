"""
Workflow format converter for expanding action-based configurations.

This module converts action-based workflow configurations into agent configurations,
handling loop expansion, template variables, and dependency mapping.
"""
from typing import Dict, Any, Optional
from .config_types import AgentConfigMap, AgentEntryDict, AgentConfigList
from .config_field_definitions import inherit_simple_fields
import logging
logger = logging.getLogger(__name__)

class ActionExpander:
    """Converts action-based workflow configurations to agent configurations with loop expansion support."""

    @staticmethod
    def detect_format(config: Dict[str, Any]) -> str:
        """
        Detect whether a config uses old or new format.

        Args:
            config: Loaded YAML configuration

        Returns:
            "old" or "new"
        """
        if 'name' in config and 'actions' in config:
            return 'new'
        for key, value in config.items():
            if isinstance(value, list) and value:
                first_item = value[0]
                if isinstance(first_item, dict) and 'agent_type' in first_item:
                    return 'old'
        return 'old'

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
        from agent_actions.utilities.vendor_config import VendorType
        from agent_actions.errors import ConfigValidationError  # New modular pattern!
        valid_vendors = [v.value for v in VendorType]
        if vendor not in valid_vendors:
            raise ConfigValidationError('model_vendor', f"Unknown vendor '{vendor}'", context={'action': action_name, 'vendor': vendor, 'supported_vendors': valid_vendors, 'hint': f"Valid vendors: {', '.join(valid_vendors)}"})

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
        from agent_actions.errors import ConfigValidationError  # New modular pattern!
        required_fields = {'model_vendor': agent.get('model_vendor'), 'model_name': agent.get('model_name'), 'api_key': agent.get('api_key')}
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            field_display_names = {'model_vendor': 'vendor/model_vendor', 'model_name': 'model/model_name', 'api_key': 'api_key'}
            missing_display = [field_display_names.get(f, f) for f in missing_fields]
            raise ConfigValidationError(config_key=', '.join(missing_fields), reason=f'Required configuration fields are missing after hierarchy resolution', context={'action_name': action_name, 'missing_fields': missing_fields, 'missing_display': missing_display, 'operation': 'expand_actions_to_agents', 'hint': 'Add missing fields to agent_actions.yml (project-level), workflow defaults, or action config'})

    @staticmethod
    def _deep_merge_context_scope(
        defaults_scope: Optional[Dict[str, Any]],
        action_scope: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Deep merge context_scope directives from defaults and action levels.

        Action-level directives are merged with (not replace) defaults directives.
        This allows actions to define drop/observe while inheriting seed_data from defaults.

        Args:
            defaults_scope: context_scope from defaults (may be None)
            action_scope: context_scope from action config (may be None)

        Returns:
            Merged context_scope dict

        Examples:
            >>> defaults = {'seed_data': {'exam': 'file.json'}}
            >>> action = {'drop': ['source.api_key']}
            >>> _deep_merge_context_scope(defaults, action)
            {'seed_data': {'exam': 'file.json'}, 'drop': ['source.api_key']}

            >>> defaults = {'observe': ['agent1.field1']}
            >>> action = {'observe': ['agent2.field2'], 'drop': ['source.id']}
            >>> _deep_merge_context_scope(defaults, action)
            {'observe': ['agent1.field1', 'agent2.field2'], 'drop': ['source.id']}
        """
        if not defaults_scope:
            return action_scope or {}
        if not action_scope:
            return defaults_scope or {}

        # Start with defaults
        merged = {**defaults_scope}

        # Merge action-level directives
        for key, value in action_scope.items():
            if key in merged:
                # Both defaults and action have this directive
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    # Deep merge for dict directives (e.g., seed_data)
                    merged[key] = {**merged[key], **value}
                elif isinstance(merged[key], list) and isinstance(value, list):
                    # Combine lists and preserve order while removing duplicates
                    # Action values come after defaults values
                    merged[key] = list(dict.fromkeys(merged[key] + value))
                else:
                    # For scalar values, action overrides defaults
                    merged[key] = value
            else:
                # New directive from action
                merged[key] = value

        return merged

    @staticmethod
    def _create_agent_from_action(action: Dict[str, Any], defaults: Dict[str, Any], agent: AgentEntryDict, template_replacer, is_operational: bool=True) -> AgentEntryDict:
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
        inherit_simple_fields(agent, action, defaults)
        agent['is_operational'] = is_operational
        ActionExpander._validate_vendor_exists(agent['model_vendor'], action.get('name', 'unknown'))
        action_kind = action.get('kind', 'llm')
        if action_kind != 'tool':
            ActionExpander._validate_required_fields(agent, action.get('name', 'unknown'))
        run_mode = agent['run_mode']
        schema_value = action.get('schema') or action.get('output_schema')
        if schema_value:
            schema_value = template_replacer(schema_value)
            if isinstance(schema_value, str):
                agent['schema_name'] = schema_value
            elif isinstance(schema_value, dict):
                agent['schema'] = schema_value
            else:
                agent['schema'] = schema_value
        if action.get('guard'):
            from agent_actions.response_processing.guard_parser import GuardParser
            from agent_actions.utilities.consolidated_guard import GuardBehavior, parse_guard_config
            guard_data = action['guard']
            if isinstance(guard_data, str):
                guard_expr = GuardParser.parse(guard_data)
                if guard_expr.type.value == 'udf':
                    agent['conditional_clause'] = guard_expr.expression
                else:
                    agent['where_clause'] = {'clause': guard_expr.expression, 'scope': 'item'}
            else:
                guard_config = parse_guard_config(guard_data)
                if guard_config.is_udf_condition():
                    if guard_config.on_false == GuardBehavior.FILTER:
                        from agent_actions.errors import ConfigurationError  # New modular pattern!
                        action_name = action.get('name', 'unknown')
                        raise ConfigurationError("UDF conditions cannot use 'filter' behavior. UDF conditions only support 'skip' behavior", context={'action_name': action_name, 'guard_behavior': 'filter', 'operation': 'expand_actions_to_agents'})
                    agent['conditional_clause'] = guard_config.get_condition_expression()
                else:
                    agent['where_clause'] = {'clause': guard_config.get_condition_expression(), 'scope': 'item', 'behavior': guard_config.on_false.value}
        prompt = action.get('prompt')
        if prompt:
            agent['prompt'] = template_replacer(prompt)
        else:
            agent['prompt'] = None
        action_kind = action.get('kind', 'llm')
        if action_kind == 'tool':
            if not action.get('impl'):
                from agent_actions.errors import ConfigValidationError  # New modular pattern!
                raise ConfigValidationError('impl', "Tool actions must specify 'impl' field", context={'action': action.get('name', 'unknown'), 'kind': 'tool', 'hint': "Add 'impl: module.function_name' to your tool action"})
            agent['model_vendor'] = 'tool'
            agent['model_name'] = action.get('impl', action.get('name'))
            if run_mode == 'batch':
                if action.get('run_mode') == 'batch':
                    from agent_actions.errors import ConfigurationError  # New modular pattern!
                    action_name = action.get('name', 'unknown')
                    raise ConfigurationError("Tool actions do not support batch processing. Please set run_mode='online' or remove the run_mode setting to use the default", context={'action_name': action_name, 'kind': 'tool', 'run_mode': 'batch', 'operation': 'expand_actions_to_agents'})
                agent['run_mode'] = 'online'
        granularity = action.get('granularity', defaults.get('granularity', 'record'))
        if granularity:
            agent['granularity'] = granularity.capitalize() if isinstance(granularity, str) else granularity
        current_granularity = agent.get('granularity', 'Record')
        # Handle context_scope (complex field - not in SIMPLE_CONFIG_FIELDS)
        # Deep merge: action directives merge with defaults (not replace)
        context_scope_defaults = defaults.get('context_scope')
        context_scope_action = action.get('context_scope')
        if context_scope_defaults or context_scope_action:
            agent['context_scope'] = ActionExpander._deep_merge_context_scope(
                context_scope_defaults,
                context_scope_action
            )

        agent['dependencies'] = []
        chunk_config = action.get('chunk_config', defaults.get('chunk_config', {}))
        if chunk_config:
            agent['chunk_config'] = chunk_config
        else:
            agent['chunk_config'] = {}
            if action.get('chunk_size') or defaults.get('chunk_size'):
                agent['chunk_config']['chunk_size'] = action.get('chunk_size', defaults.get('chunk_size', 300))
            if action.get('chunk_overlap') or defaults.get('chunk_overlap'):
                agent['chunk_config']['chunk_overlap'] = action.get('chunk_overlap', defaults.get('chunk_overlap', 10))
        agent['skip_if'] = None
        agent['ephemeral'] = None
        agent['add_dispatch'] = None
        agent['anthropic_version'] = None
        agent['enable_prompt_caching'] = None
        if 'conditional_clause' not in agent:
            agent['conditional_clause'] = None
        if 'where_clause' not in agent:
            agent['where_clause'] = None
        loop_consumption = action.get('loop_consumption')
        if loop_consumption:
            agent['loop_consumption_config'] = {'source': loop_consumption.get('source'), 'pattern': loop_consumption.get('pattern', 'merge')}
        else:
            agent['loop_consumption_config'] = None
        interceptors = action.get('interceptors')
        if interceptors:
            agent['interceptors'] = interceptors
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
        workflow_name = action_config.get('name', 'workflow')
        actions = action_config.get('actions', [])
        defaults = action_config.get('defaults', {})
        plan = action_config.get('plan', [])
        actions_in_plan = set()
        for plan_item in plan:
            if '<-' in plan_item:
                action_name = plan_item.split('<-')[0].strip()
            else:
                action_name = plan_item.strip()
            actions_in_plan.add(action_name)
        agents: AgentConfigList = []
        for action in actions:
            action_name = action.get('name')
            is_in_plan = action_name in actions_in_plan
            if not is_in_plan:
                continue
            loop_config = action.get('loop')
            if loop_config:
                param_name = loop_config.get('param', 'i')
                loop_range = loop_config.get('range', [1, 1])
                if len(loop_range) == 2:
                    start, end = loop_range
                    range_values = range(start, end + 1)
                else:
                    range_values = loop_range
                range_values_list = list(range_values)
                for idx, i in enumerate(range_values_list):
                    agent: AgentEntryDict = {}

                    def replace_template_var(value):
                        if isinstance(value, str):
                            result = value.replace(f'${{{param_name}}}', str(i))
                            if idx > 0:
                                prev_value = range_values_list[idx - 1]
                                result = result.replace(f'${{{param_name}-1}}', str(prev_value))
                            else:
                                result = result.replace(f'${{{param_name}-1}}', '')
                            return result
                        elif isinstance(value, dict):
                            return {replace_template_var(k) if isinstance(k, str) else k: replace_template_var(v) for k, v in value.items()}
                        elif isinstance(value, list):
                            return [replace_template_var(item) for item in value]
                        return value
                    agent['agent_type'] = f"{action.get('name', 'unknown')}_{i}"
                    agent['name'] = f"{action.get('name')}_{i}"
                    agent['is_loop_agent'] = True
                    agent['loop_base_name'] = action.get('name', 'unknown')
                    agent['loop_iteration'] = i
                    agent['loop_mode'] = loop_config.get('mode', 'parallel')
                    agents.append(ActionExpander._create_agent_from_action(action, defaults, agent, replace_template_var, is_operational=is_in_plan))
            else:
                agent: AgentEntryDict = {}
                agent['agent_type'] = action.get('name', 'unknown')
                agent['name'] = action.get('name')
                agents.append(ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x, is_operational=True))
        plan = action_config.get('plan', [])
        action_loop_configs = {}
        for action in actions:
            action_name = action.get('name')
            loop_config = action.get('loop')
            if loop_config:
                action_loop_configs[action_name] = loop_config
        agent_name_to_indices = {}
        agent_index = 0
        for action in actions:
            action_name = action.get('name')
            loop_config = action.get('loop')
            if loop_config:
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
                if action_name in agent_name_to_indices:
                    expanded_deps = []
                    for dep in deps:
                        if dep in agent_name_to_indices:
                            for dep_idx in agent_name_to_indices[dep]:
                                expanded_deps.append(agents[dep_idx]['agent_type'])
                        else:
                            expanded_deps.append(dep)
                    loop_config = action_loop_configs.get(action_name)
                    if loop_config and loop_config.get('mode') == 'sequential':
                        for i, agent_idx in enumerate(agent_name_to_indices[action_name]):
                            if i == 0:
                                agents[agent_idx]['dependencies'] = expanded_deps
                            else:
                                prev_idx = agent_name_to_indices[action_name][i - 1]
                                agents[agent_idx]['dependencies'] = [agents[prev_idx]['agent_type']]
                    else:
                        for agent_idx in agent_name_to_indices[action_name]:
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
        format_type = ActionExpander.detect_format(config)
        if format_type == 'new':
            logger.info('Detected new workflow format, converting to old format for execution')
            return ActionExpander.convert_new_to_old(config)
        else:
            logger.debug('Using existing old format configuration')
            return config
__all__ = ['ActionExpander']
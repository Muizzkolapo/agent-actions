"""Migration logic for converting old workflow format to new format."""

import re
import yaml
from typing import Dict, Any, List, Optional, Union
from .new_format_schema import (
    WorkflowConfigV2, ActionConfig, DefaultsConfig,
    ActionKind, Granularity
)
from agent_actions.input_loading.template_yaml_loader import TemplateYamlLoader


class WorkflowMigrator:
    """Migrates workflow configurations from old format to new format."""

    def __init__(self):
        self.template_pattern = re.compile(r'\{\{\s*(\w+)\((.*?)\)\s*\}\}', re.DOTALL)
        self.yaml_loader = TemplateYamlLoader()

    def migrate_workflow(self, old_config: Dict[str, Any]) -> WorkflowConfigV2:
        """Migrate a complete workflow configuration."""
        # Extract workflow name (first key in old config)
        workflow_name = list(old_config.keys())[0]
        workflow_data = old_config[workflow_name]

        # Extract defaults from common patterns
        defaults = self._extract_defaults(workflow_data)

        # Transform agents to actions
        actions = []
        dependencies = {}

        for agent_config in workflow_data:
            if isinstance(agent_config, dict):
                action, deps = self._transform_agent_to_action(agent_config, defaults)
                if action:
                    actions.append(action)
                    if deps:
                        dependencies[action.name] = deps

        # Generate execution plan
        plan = self._generate_execution_plan(actions, dependencies)

        return WorkflowConfigV2(
            name=workflow_name,
            description=f"Migrated workflow: {workflow_name}",
            version="2.0.0",
            defaults=defaults,
            actions=actions,
            plan=plan
        )

    def _extract_defaults(self, workflow_data: List[Dict[str, Any]]) -> DefaultsConfig:
        """Extract common defaults from agent configurations."""
        vendors = []
        models = []
        json_modes = []
        run_modes = []
        granularities = []

        for agent in workflow_data:
            if isinstance(agent, dict):
                if 'model_vendor' in agent:
                    vendors.append(agent['model_vendor'])
                if 'model_name' in agent:
                    models.append(agent['model_name'])
                if 'json_mode' in agent:
                    json_modes.append(agent['json_mode'])
                if 'run_mode' in agent:
                    run_modes.append(agent['run_mode'])
                if 'granularity' in agent:
                    granularities.append(agent['granularity'])

        # Use most common values as defaults
        return DefaultsConfig(
            vendor=self._most_common(vendors),
            model=self._most_common(models),
            json_mode=self._most_common(json_modes),
            run_mode=self._most_common(run_modes),
            granularity=self._most_common(granularities)
        )

    def _most_common(self, items: List[Any]) -> Optional[Any]:
        """Get the most common item in a list."""
        if not items:
            return None
        most_common = max(set(items), key=items.count)

        # Handle granularity case normalization
        if isinstance(most_common, str) and most_common.lower() in ('record', 'file'):
            return most_common.lower()

        return most_common

    def _transform_agent_to_action(self, agent: Dict[str, Any], defaults: DefaultsConfig) -> tuple[Optional[ActionConfig], List[str]]:
        """Transform a single agent configuration to an action."""

        # Handle template-based agents
        if self._is_template_agent(agent):
            return self._handle_template_agent(agent)

        # Regular agent transformation
        agent_type = agent.get('agent_type')
        if not agent_type:
            return None, []

        # Generate action name from agent_type
        action_name = self._generate_action_name(agent_type)

        # Determine action kind
        kind = ActionKind.TOOL if agent.get('model_vendor') == 'tool' else ActionKind.LLM

        # Extract data flow
        reads, writes, drops, observe = self._extract_data_flow(agent)

        # Extract execution settings
        granularity = self._map_granularity(agent.get('granularity'))
        guard = self._convert_where_clause(agent.get('where_clause'))

        # Extract dependencies
        dependencies = agent.get('dependencies', [])

        # Build action config
        action = ActionConfig(
            name=action_name,
            intent=self._generate_intent(agent_type),
            kind=kind,
            model_vendor=agent.get('model_vendor') if agent.get('model_vendor') != defaults.model_vendor else None,
            model_name=agent.get('model_name') if agent.get('model_name') != defaults.model_name else None,
            output_schema=self._extract_schema(agent),
            reads=list(set(reads)) if reads else [],  # Deduplicate
            writes=list(set(writes)) if writes else [],  # Deduplicate
            drops=list(set(drops)) if drops else [],  # Deduplicate
            observe=list(set(observe)) if observe else [],  # Deduplicate
            granularity=granularity,
            guard=guard,
            few_shot=agent.get('few_shot') if agent.get('few_shot', 0) > 0 else None,
            prompt=agent.get('prompt')
        )

        return action, dependencies

    def _is_template_agent(self, agent: Dict[str, Any]) -> bool:
        """Check if agent uses template syntax."""
        return 'template_type' in agent

    def _handle_template_agent(self, agent: Dict[str, Any]) -> tuple[Optional[ActionConfig], List[str]]:
        """Handle template-based workflow agents."""
        template_type = agent.get('template_type')

        if not template_type:
            return None, []

        action_name = agent.get('agent_type', f"tool_{template_type}")

        # Extract dependencies
        dependencies = agent.get('dependencies', [])
        if isinstance(dependencies, str):
            dependencies = [dep.strip().strip('"\'') for dep in dependencies.split(',')]

        # Create tool action
        action = ActionConfig(
            name=action_name,
            intent=agent.get('description', f"Custom {template_type} tool"),
            kind=ActionKind.TOOL,
            impl=agent.get('model_name', action_name),
            granularity=self._map_granularity(agent.get('granularity')),
            guard=self._convert_where_clause(agent.get('where_clause')),
            reads=self._parse_collection_list(agent.get('observe', [])),
            writes=self._infer_writes_from_tool(action_name)
        )

        return action, dependencies

    def _parse_template_params(self, params_str: str) -> Dict[str, Any]:
        """Parse template parameters from string."""
        param_dict = {}

        # Handle simple key=value pairs
        for param in params_str.split(','):
            param = param.strip()
            if '=' in param:
                key, value = param.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')

                # Convert to appropriate types
                if value.lower() in ('true', 'false'):
                    value = value.lower() == 'true'
                elif value.startswith('[') and value.endswith(']'):
                    # Handle list values
                    value = [item.strip().strip('"\'') for item in value[1:-1].split(',') if item.strip()]

                param_dict[key] = value

        return param_dict

    def _parse_collection_list(self, collection: Union[str, List[str]]) -> List[str]:
        """Parse collection field lists."""
        if isinstance(collection, str):
            if collection.startswith('[') and collection.endswith(']'):
                return [item.strip().strip('"\'') for item in collection[1:-1].split(',') if item.strip()]
            return [collection] if collection else []
        return collection or []

    def _extract_data_flow(self, agent: Dict[str, Any]) -> tuple[List[str], List[str], List[str], List[str]]:
        """Extract data flow configuration from agent."""
        observe = self._parse_collection_list(agent.get('observe', []))
        drops = self._parse_collection_list(agent.get('drops', []))

        # Infer reads from observe
        reads = observe.copy()

        # Infer writes from schema or agent type
        writes = self._infer_writes_from_agent(agent)

        # drops are items to remove
        drops = drops

        # observe includes observe items that aren't consumed
        observe = observe.copy()

        return reads, writes, drops, observe

    def _infer_writes_from_agent(self, agent: Dict[str, Any]) -> List[str]:
        """Infer output fields from agent configuration."""
        writes = []

        # From schema
        schema = agent.get('schema') or agent.get('schema_name')
        if schema:
            if isinstance(schema, dict):
                writes.extend(schema.keys())
            elif isinstance(schema, str):
                writes.append(self._schema_name_to_field(schema))

        # From agent type patterns
        agent_type = agent.get('agent_type', '')
        if 'fact' in agent_type.lower():
            writes.append('candidate_facts_list')
        elif 'cluster' in agent_type.lower():
            writes.extend(['clusters', 'cluster_validation'])
        elif 'explanation' in agent_type.lower():
            writes.append('fact_explanation')
        elif 'classif' in agent_type.lower():
            writes.extend(['quiz_type', 'rationale'])
        elif 'scenario' in agent_type.lower():
            writes.extend(['scenario', 'question', 'options_answer', 'question_type'])

        return writes

    def _infer_writes_from_tool(self, tool_name: str) -> List[str]:
        """Infer output fields from tool name."""
        if 'cluster' in tool_name.lower():
            return ['clusters']
        elif 'combine' in tool_name.lower():
            return ['combined_items', 'flagged_items']
        elif 'split' in tool_name.lower():
            return ['refined_clusters']
        return ['result']

    def _schema_name_to_field(self, schema_name: str) -> str:
        """Convert schema name to field name."""
        # Remove common suffixes/prefixes
        field = schema_name.replace('_schema', '').replace('Schema', '')
        return field.lower()

    def _generate_action_name(self, agent_type: str) -> str:
        """Generate action name from agent type."""
        # Convert CamelCase or snake_case to action names
        name = re.sub(r'([A-Z])', r'_\1', agent_type).lower()
        name = name.strip('_').replace('__', '_')

        # Map common agent types to action names
        name_mappings = {
            'fact_extractor': 'extract_facts',
            'cluster_validation_agent': 'validate_clusters',
            'fact_explanations': 'explain_facts',
            'classifer_feynman': 'classify_feynman',
            'scenariogenerator': 'generate_scenarios'
        }

        return name_mappings.get(name, name)

    def _generate_intent(self, agent_type: str) -> str:
        """Generate intent description from agent type."""
        intent_mappings = {
            'fact_extractor': 'Identify candidate facts from source content',
            'cluster_validation_agent': 'Validate cluster quality and flag problematic items',
            'fact_explanations': 'Generate explanations for extracted facts',
            'classifer_feynman': 'Classify quiz type using Feynman technique',
            'scenariogenerator': 'Generate quiz scenarios based on classified facts'
        }

        return intent_mappings.get(agent_type, f"Execute {agent_type} processing")

    def _map_granularity(self, granularity: Optional[str]) -> Optional[Granularity]:
        """Map old granularity to new enum."""
        if not granularity:
            return None

        granularity_lower = granularity.lower()
        if granularity_lower == 'record':
            return Granularity.RECORD
        elif granularity_lower == 'file':
            return Granularity.FILE

        return None

    def _convert_where_clause(self, where_clause: Optional[Dict[str, Any]]) -> Optional[str]:
        """Convert old where_clause to new guard format."""
        if not where_clause:
            return None

        if isinstance(where_clause, dict):
            clause = where_clause.get('clause')
            if clause:
                return clause

        return None

    def _extract_schema(self, agent: Dict[str, Any]) -> Optional[Union[str, Dict[str, Any]]]:
        """Extract schema configuration."""
        schema = agent.get('schema') or agent.get('schema_name')
        return schema

    def _generate_execution_plan(self, actions: List[ActionConfig], dependencies: Dict[str, List[str]]) -> List[str]:
        """Generate execution plan with dependencies."""
        plan = []

        # Create mapping from old agent names to new action names
        action_name_map = {}
        for action in actions:
            # Try to find the original agent name this action came from
            for old_name, new_name in [
                ('fact_extractor', 'extract_facts'),
                ('Cluster_Validation_Agent', 'validate_clusters'),
                ('fact_explanations', 'explain_facts'),
                ('classifer_feynman', 'classify_feynman'),
                ('ScenarioGenerator', 'scenario_generator')
            ]:
                if action.name == new_name:
                    action_name_map[old_name] = new_name

        for action in actions:
            deps = dependencies.get(action.name, [])
            if deps:
                # Map old dependency names to new action names
                mapped_deps = []
                for dep in deps:
                    mapped_dep = action_name_map.get(dep, dep)
                    mapped_deps.append(mapped_dep)
                plan.append(f"{action.name} <- {', '.join(mapped_deps)}")
            else:
                plan.append(action.name)

        return plan

    def migrate_from_yaml_file(self, file_path: str) -> WorkflowConfigV2:
        """Migrate workflow from YAML file."""
        old_config = self.yaml_loader.load_template_yaml(file_path)
        return self.migrate_workflow(old_config)

    def save_migrated_workflow(self, workflow: WorkflowConfigV2, output_path: str):
        """Save migrated workflow to YAML file."""
        workflow_dict = workflow.model_dump(exclude_none=True, mode='json')

        # Convert enum values to strings for clean YAML output
        self._clean_dict_for_yaml(workflow_dict)

        with open(output_path, 'w') as f:
            yaml.dump(workflow_dict, f, default_flow_style=False, sort_keys=False, indent=2)

    def _clean_dict_for_yaml(self, obj):
        """Recursively clean dictionary for clean YAML serialization."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, (dict, list)):
                    self._clean_dict_for_yaml(value)
                elif hasattr(value, 'value'):  # Enum
                    obj[key] = value.value
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    self._clean_dict_for_yaml(item)
                elif hasattr(item, 'value'):  # Enum
                    obj[i] = item.value


__all__ = ["WorkflowMigrator"]
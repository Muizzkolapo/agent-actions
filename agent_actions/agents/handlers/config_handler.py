"""Module for Configuration Validation Functions."""
import yaml
from pathlib import Path
from pydantic import ValidationError
from agent_actions.core.core_utils import Utils
from agent_actions.core.graph.render_workflow import render_pipeline_with_templates
from agent_actions.agents.validators.config_validator import ConfigValidator
from agent_actions.agents.validators.input_signature_validator import InputSignatureValidator
from typing import Dict, Any, Optional, List
from agent_actions.core.exceptions import ConfigurationError, TemplateRenderingError, ConfigValidationError
from agent_actions.core.parser.config_schema import AgentConfig, DefaultAgentConfig
from agent_actions.core.context.environment_config import EnvironmentConfig
from agent_actions.core.parser.pipeline_config import WorkflowConfig, PipelineConfig
from agent_actions.core.context.path_config import load_project_config
from agent_actions.core.context.path_manager import PathManager
from agent_actions.core.parser.action_expander import ActionExpander
from agent_actions.core.safe_format import safe_format_error



class ConfigManager:
    def __init__(self, constructor_path: str, default_path: str):
        self.constructor_path = constructor_path
        self.default_path = default_path
        self.user_config: Optional[Dict[str, Any]] = None
        self.default_config: Optional[Dict[str, Any]] = None
        self.agent_name: Optional[str] = None
        self.agent_configs: Dict[str, AgentConfig] = {}
        self.execution_order: List[str] = []
        self.child_pipeline: Optional[str] = None
        self.tool_path: Optional[str] = None
        self.template_dir = str(Path.cwd() / "templates")
        
        # New typed configurations
        self.environment_config: Optional[EnvironmentConfig] = None
        self.workflow_config: Optional[WorkflowConfig] = None
        self.pipeline_config: Optional[PipelineConfig] = None

    def load_configs(self):
        try:
            config_data = render_pipeline_with_templates(self.constructor_path, self.template_dir)
            loaded_config = yaml.safe_load(config_data)

            # Expect new format only
            self.user_config = loaded_config
        except (TemplateRenderingError, ConfigurationError) as e: # Catch specific errors from render_pipeline
            raise ConfigurationError(
                "Error rendering or loading user config",
                context={'config_path': str(self.constructor_path), 'operation': 'load_user_config'},
                cause=e
            )
        except yaml.YAMLError as e:
            raise ConfigurationError(
                "Error parsing YAML for user config",
                context={'config_path': str(self.constructor_path), 'operation': 'parse_yaml'},
                cause=e
            )
        except Exception as e: # Catch other unexpected errors
            raise ConfigurationError(
                "Unexpected error loading user config",
                context={'config_path': str(self.constructor_path), 'operation': 'load_user_config'},
                cause=e
            )

        try:
            default_config_data = render_pipeline_with_templates(self.default_path, self.template_dir)
            self.default_config = yaml.safe_load(default_config_data)
        except (TemplateRenderingError, ConfigurationError) as e: # Catch specific errors from render_pipeline
            raise ConfigurationError(
                "Error rendering or loading default config",
                context={'config_path': str(self.default_path), 'operation': 'load_default_config'},
                cause=e
            )
        except yaml.YAMLError as e:
            raise ConfigurationError(
                "Error parsing YAML for default config",
                context={'config_path': str(self.default_path), 'operation': 'parse_yaml'},
                cause=e
            )
        except Exception as e: # Catch other unexpected errors
            raise ConfigurationError(
                "Unexpected error loading default config",
                context={'config_path': str(self.default_path), 'operation': 'load_default_config'},
                cause=e
            )

        # Prioritize tool_path from user_config, then fallback to default_config
        user_tool_path = None
        if isinstance(self.user_config, dict):
            user_tool_path = self.user_config.get("tool_path") or self.user_config.get("tool")

        default_tool_path = None
        if isinstance(self.default_config, dict):
            default_tool_path = self.default_config.get("tool_path") or self.default_config.get("tool")

        if user_tool_path is not None:
            self.tool_path = user_tool_path
        else:
            self.tool_path = default_tool_path

    def find_agent_name(self,config: Dict[str, Any]) -> str:
        """
        Find the name of the agent from the configuration.

        Args:
            config: Agent configuration dictionary

        Returns:
            str: Name of the agent
        """
        # Check if this is new format
        if 'name' in config and 'actions' in config:
            return config['name']
        else:
            # Old format - return first key (workflow name)
            return next(iter(config)) 
    
    def validate_agent_name(self):
        self.agent_name = self.find_agent_name(self.user_config)
        config_filename = Path(self.constructor_path).stem
        if self.agent_name != config_filename:
            raise ConfigurationError(
                "Top-level key does not match the filename",
                context={'agent_name': self.agent_name, 'config_filename': config_filename, 'operation': 'validate_agent_name'}
            )

    def check_child_pipeline(self):
        # Check if this is new format
        if 'name' in self.user_config and 'actions' in self.user_config:
            # New format - check actions for child pipelines
            actions = self.user_config.get('actions', [])
            for action in actions:
                if isinstance(action, dict) and 'child' in action:
                    self.child_pipeline = action['child'][0]
                    return
        else:
            # Old format - original logic
            agent_list = self.user_config.get(self.agent_name, [])
            for item in agent_list:
                if isinstance(item, dict) and 'child' in item:
                    self.child_pipeline = item['child'][0]
                    return
        self.child_pipeline = None

    def get_user_agents(self):
        # Check if this is action-based format
        if 'name' in self.user_config and 'actions' in self.user_config:
            # Load project-level defaults from agent_actions.yml
            try:
                path_manager = PathManager()
                project_root = path_manager.get_project_root()
                project_config = load_project_config(project_root)
                project_defaults = project_config.get('default_agent_config', {})
            except Exception:
                # If project config can't be loaded, continue without it
                project_defaults = {}

            # Get workflow-level defaults
            workflow_defaults = self.user_config.get('defaults', {})

            # Create merged defaults: project < workflow (workflow overrides project)
            merged_defaults = {**project_defaults, **workflow_defaults}

            # Create a modified config with merged defaults for the converter
            config_with_merged_defaults = {
                **self.user_config,
                'defaults': merged_defaults
            }

            # Use ActionExpander to handle loop expansion and action conversion
            agent_config_map = ActionExpander.expand_actions_to_agents(config_with_merged_defaults)

            # Extract the agents list from the returned map (workflow_name -> agents)
            workflow_name = self.user_config.get('name', 'workflow')
            user_agents = agent_config_map.get(workflow_name, [])

            return user_agents
        else:
            # Old format - original logic
            agents_section = self.user_config[self.agent_name]
            if 'agents' in agents_section:
                user_agents = agents_section['agents']
            else:
                user_agents = [agent for agent in agents_section if isinstance(agent, dict) and 'agent_type' in agent]
            return user_agents

    def merge_agent_configs(self, user_agents: List[Dict[str, Any]]) -> None:
        default_model = DefaultAgentConfig.model_validate(
            self.default_config.get('default_agent_config', {}) if self.default_config else {}
        )
        default_agent_config = default_model.model_dump()

        for agent in user_agents:
            try:
                agent_model = AgentConfig.model_validate(agent)
            except ValidationError as e:
                raise ConfigurationError(
                    "Invalid agent configuration",
                    context={'agent_type': agent.get('agent_type', 'unknown'), 'operation': 'merge_agent_configs'},
                    cause=e
                )

            agent_type = agent_model.agent_type
            # Merge default config with agent-specific config
            agent_dict = agent_model.model_dump(exclude_unset=True)

            # Deep merge for nested configs like chunk_config
            merged_dict = {**default_agent_config}
            for key, value in agent_dict.items():
                if key == 'chunk_config' and isinstance(value, dict):
                    # Deep merge chunk_config - ensure default_chunk is always a dict
                    default_chunk = merged_dict.get(key)
                    if not isinstance(default_chunk, dict):
                        default_chunk = {}
                    merged_dict[key] = {**default_chunk, **value}
                else:
                    merged_dict[key] = value

            # Create a validated AgentConfig from the merged dictionary
            merged_agent_config = AgentConfig.model_validate(merged_dict)
            self.agent_configs[agent_type] = merged_agent_config

    def determine_execution_order(self, user_agents: List[Dict[str, Any]]) -> None:
        """
        Determines the execution order of agents based on their dependencies,
        considering only is_operational agents.
        """
        instance_config = ConfigValidator()
        # Convert AgentConfig models to dictionaries for validator compatibility
        agent_configs_dict = {
            agent_type: config.model_dump() 
            for agent_type, config in self.agent_configs.items()
        }
        instance_config.validate(agent_configs_dict)
        
        dependency_graph = {}
        for agent_type, config in self.agent_configs.items():
            if config.is_operational:
                dependencies = [
                    dep for dep in config.dependencies
                    if dep in self.agent_configs and self.agent_configs[dep].is_operational
                ]
                dependency_graph[agent_type] = dependencies

        # Validate input signatures (field references in prompts)
        self._validate_input_signatures(dependency_graph)

        self.execution_order = Utils.topological_sort(dependency_graph)
    
    def load_environment_config(self) -> EnvironmentConfig:
        """Load and validate environment configuration."""
        try:
            self.environment_config = EnvironmentConfig()
            return self.environment_config
        except ValidationError as e:
            raise ConfigurationError(
                "Invalid environment configuration",
                context={'operation': 'load_environment_config'},
                cause=e
            )
    
    def get_agent_config(self, agent_type: str) -> Optional[AgentConfig]:
        """Get typed agent configuration by agent type."""
        return self.agent_configs.get(agent_type)
    
    def get_all_agent_configs(self) -> Dict[str, AgentConfig]:
        """Get all typed agent configurations."""
        return self.agent_configs.copy()
    
    def get_all_agent_configs_as_dicts(self) -> Dict[str, Dict[str, Any]]:
        """Get all agent configurations as dictionaries for backward compatibility."""
        result = {}
        for agent_type, config in self.agent_configs.items():
            # Get the dictionary representation and filter out None values for optional string fields
            config_dict = config.model_dump()
            
            # Replace None values with appropriate defaults for backward compatibility
            string_fields_with_defaults = {
                'conditional_clause': '',
                'model_vendor': '',
                'granularity': 'record',
                'run_mode': 'online',
                'prompt': '',
                'schema_name': '',
                'code_path': '',
                'data_source': '',
                'anthropic_version': '',
            }
            
            for field, default_value in string_fields_with_defaults.items():
                if field in config_dict and config_dict[field] is None:
                    config_dict[field] = default_value
            
            result[agent_type] = config_dict
        
        return result
    
    def create_workflow_config(self, workflow_data: Dict[str, Any]) -> WorkflowConfig:
        """Create a typed workflow configuration from dictionary data."""
        try:
            self.workflow_config = WorkflowConfig.model_validate(workflow_data)
            return self.workflow_config
        except ValidationError as e:
            raise ConfigurationError(
                "Invalid workflow configuration",
                context={'workflow_name': workflow_data.get('name', 'unknown'), 'operation': 'create_workflow_config'},
                cause=e
            )
    
    def create_pipeline_config(self, pipeline_data: Dict[str, Any]) -> PipelineConfig:
        """Create a typed pipeline configuration from dictionary data."""
        try:
            self.pipeline_config = PipelineConfig.model_validate(pipeline_data)
            return self.pipeline_config
        except ValidationError as e:
            raise ConfigurationError(
                "Invalid pipeline configuration",
                context={'pipeline_name': pipeline_data.get('name', 'unknown'), 'operation': 'create_pipeline_config'},
                cause=e
            )
    
    def validate_all_configs(self) -> None:
        """Validate all loaded configurations."""
        if not self.environment_config:
            self.load_environment_config()
        
        # Validate agent configurations
        for agent_type, config in self.agent_configs.items():
            try:
                # Re-validate to ensure consistency
                AgentConfig.model_validate(config.model_dump())
            except ValidationError as e:
                raise ConfigurationError(
                    "Agent configuration is invalid",
                    context={'agent_type': agent_type, 'operation': 'validate_all_configs'},
                    cause=e
                )
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get a summary of all loaded configurations."""
        return {
            "environment": {
                "loaded": self.environment_config is not None,
                "env": self.environment_config.agent_actions_env if self.environment_config else None
            },
            "agents": {
                "count": len(self.agent_configs),
                "types": list(self.agent_configs.keys()),
                "execution_order": self.execution_order
            },
            "workflow": {
                "loaded": self.workflow_config is not None,
                "name": self.workflow_config.name if self.workflow_config else None
            },
            "pipeline": {
                "loaded": self.pipeline_config is not None,
                "name": self.pipeline_config.name if self.pipeline_config else None
            }
        }

    def _validate_input_signatures(self, dependency_graph: Dict[str, List[str]]) -> None:
        """
        Validate that field references in agent prompts match available LLM context.

        This validates that when agents reference fields from dependencies (like {extractor.summary}),
        those fields will actually be available in the next agent's LLM context based on
        output schema, observe, and drops directives.

        Args:
            dependency_graph: Dict mapping agent names to their dependency lists

        Raises:
            ConfigValidationError: If any agent has invalid field references in its prompt
        """
        validator = InputSignatureValidator()
        all_errors = []

        for agent_name, dependencies in dependency_graph.items():
            # Get agent config
            if agent_name not in self.agent_configs:
                continue

            agent_config = self.agent_configs[agent_name].model_dump()

            # Build dependency configs dict
            dependency_configs = {}
            for dep_name in dependencies:
                if dep_name in self.agent_configs:
                    dependency_configs[dep_name] = self.agent_configs[dep_name].model_dump()

            # Validate this agent's input signature
            result = validator.validate_agent_inputs(agent_config, dependency_configs, agent_name)

            if result.has_errors():
                all_errors.append((agent_name, result))

        # If any errors found, format and raise
        if all_errors:
            error_message = self._format_input_validation_errors(all_errors)
            raise ConfigValidationError(
                config_key="input_signatures",
                reason="Field references in prompts do not match available LLM context",
                context={
                    'operation': 'validate_input_signatures',
                    'agents_with_errors': [agent_name for agent_name, _ in all_errors],
                    'error_details': error_message
                }
            )

    def _format_input_validation_errors(self, errors: List[tuple]) -> str:
        """
        Format input signature validation errors as a human-readable string.

        Args:
            errors: List of (agent_name, ValidationResult) tuples

        Returns:
            Formatted error message string
        """
        lines = ["\n" + "="*80]
        lines.append("INPUT SIGNATURE VALIDATION ERRORS")
        lines.append("="*80 + "\n")

        for agent_name, validation_result in errors:
            lines.append(f"Agent: '{agent_name}'")
            lines.append("-" * 80)

            for error in validation_result.errors:
                lines.append(f"\n  ❌ {error.field_reference}")
                lines.append(f"     {error.message}")
                if error.help_text:
                    lines.append(f"     → {error.help_text}")

            lines.append("\n")

        lines.append("="*80)
        lines.append("Fix these errors in your agent configurations before running the workflow.")
        lines.append("="*80 + "\n")

        return "\n".join(lines)

    def get_all_signatures(self, schema_registry: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        """Get input and output signatures for all agents in the workflow.
        
        Returns complete signature information for every agent, enabling
        workflow-level analysis and visualization.
        
        Args:
            schema_registry: Optional registry for resolving schema references
            
        Returns:
            Dict mapping agent names to their signature information:
            {
                'agent_name': {
                    'input_signature': InputSignature,
                    'output_signature': OutputSignature,
                    'dependencies': List[str],
                    'execution_order_index': int
                }
            }
        """
        signatures = {}
        
        for agent_name, agent_config in self.agent_configs.items():
            try:
                # Build dependency configs for this agent
                dependency_configs = {}
                for dep_name in agent_config.dependencies:
                    if dep_name in self.agent_configs:
                        dependency_configs[dep_name] = self.agent_configs[dep_name]
                
                # Get signatures using Phase 2 APIs
                input_sig = agent_config.input_signature(dependency_configs, schema_registry)
                output_sig = agent_config.output_signature(schema_registry)
                
                # Get execution order index (if available)
                execution_index = -1
                if agent_name in self.execution_order:
                    execution_index = self.execution_order.index(agent_name)
                
                signatures[agent_name] = {
                    'input_signature': input_sig,
                    'output_signature': output_sig,
                    'dependencies': agent_config.dependencies.copy(),
                    'execution_order_index': execution_index,
                    'is_operational': agent_config.is_operational
                }
                
            except Exception as e:
                # If signature computation fails, include error info
                signatures[agent_name] = {
                    'error': f"Failed to compute signatures: {str(e)}",
                    'dependencies': getattr(agent_config, 'dependencies', []),
                    'execution_order_index': -1,
                    'is_operational': getattr(agent_config, 'is_operational', True)
                }
        
        return signatures

    def validate_field_flow(self, schema_registry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate complete field flow through the entire workflow.
        
        Performs comprehensive field dependency validation across all agents
        following execution order, tracking field availability as it progresses.
        
        Args:
            schema_registry: Optional registry for resolving schema references
            
        Returns:
            Dict with validation results:
            {
                'valid': bool,
                'errors': List[str],
                'warnings': List[str],
                'agent_validations': Dict[str, Dict],
                'field_flow_summary': Dict[str, Set[str]]
            }
        """
        from agent_actions.core.signature_computer import SignatureComputer
        
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'agent_validations': {},
            'field_flow_summary': {}
        }
        
        # Track available fields at each step
        available_fields = set()  # Fields available from previous agents
        
        # Process agents in execution order
        for agent_name in self.execution_order:
            if agent_name not in self.agent_configs:
                result['errors'].append(f"Agent '{agent_name}' in execution order but not in configs")
                result['valid'] = False
                continue
                
            agent_config = self.agent_configs[agent_name]
            agent_validation = {
                'valid': True,
                'errors': [],
                'warnings': [],
                'available_fields_before': available_fields.copy()
            }
            
            try:
                # Build dependency configs
                dependency_configs = {}
                dependency_signatures = {}
                
                for dep_name in agent_config.dependencies:
                    if dep_name in self.agent_configs:
                        dependency_configs[dep_name] = self.agent_configs[dep_name]
                        dep_output = self.agent_configs[dep_name].output_signature(schema_registry)
                        dependency_signatures[dep_name] = dep_output
                
                # Get this agent's signatures
                input_sig = agent_config.input_signature(dependency_configs, schema_registry)
                output_sig = agent_config.output_signature(schema_registry)
                
                # Validate field availability using existing SignatureComputer
                validation = SignatureComputer.validate_field_availability(input_sig, dependency_signatures)
                
                if not validation['valid']:
                    agent_validation['valid'] = False
                    agent_validation['errors'].extend(validation['errors'])
                    result['valid'] = False
                    result['errors'].extend([f"{agent_name}: {error}" for error in validation['errors']])
                
                # Update available fields with this agent's output
                agent_available_fields = output_sig.get_available_fields()
                available_fields.update(agent_available_fields)
                
                agent_validation['output_fields'] = agent_available_fields
                agent_validation['required_fields'] = input_sig.get_all_fields()
                
            except Exception as e:
                agent_validation['valid'] = False
                agent_validation['errors'].append(f"Error computing signatures: {str(e)}")
                result['valid'] = False
                result['errors'].append(f"{agent_name}: Error computing signatures: {str(e)}")
            
            result['agent_validations'][agent_name] = agent_validation
            result['field_flow_summary'][agent_name] = available_fields.copy()
        
        return result

    def detect_field_conflicts(self, agent_name: str, schema_registry: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
        """Detect field name conflicts between dependencies.
        
        Identifies cases where multiple dependency agents provide fields
        with the same name, which could cause ambiguity in field references.
        
        Args:
            agent_name: Name of the agent to check for conflicts
            schema_registry: Optional registry for resolving schema references
            
        Returns:
            Dict with conflict information:
            {
                'conflicts': {
                    'field_name': ['provider1', 'provider2', ...]
                },
                'all_available_fields': {
                    'dependency_name': Set[field_names]
                },
                'agent_dependencies': List[str]
            }
        """
        if agent_name not in self.agent_configs:
            return {
                'error': f"Agent '{agent_name}' not found in configurations",
                'conflicts': {},
                'all_available_fields': {},
                'agent_dependencies': []
            }
        
        agent_config = self.agent_configs[agent_name]
        conflicts = {}
        all_available_fields = {}
        field_providers = {}  # field_name -> list of providers
        
        # Analyze each dependency's output fields
        for dep_name in agent_config.dependencies:
            if dep_name not in self.agent_configs:
                continue
                
            try:
                dep_config = self.agent_configs[dep_name]
                dep_output = dep_config.output_signature(schema_registry)
                dep_fields = dep_output.get_available_fields()
                
                all_available_fields[dep_name] = dep_fields
                
                # Track which dependencies provide each field
                for field_name in dep_fields:
                    if field_name not in field_providers:
                        field_providers[field_name] = []
                    field_providers[field_name].append(dep_name)
                    
            except Exception as e:
                all_available_fields[dep_name] = f"Error: {str(e)}"
        
        # Find conflicts (fields provided by multiple dependencies)
        for field_name, providers in field_providers.items():
            if len(providers) > 1:
                conflicts[field_name] = providers
        
        return {
            'conflicts': conflicts,
            'all_available_fields': all_available_fields,
            'agent_dependencies': agent_config.dependencies.copy()
        }


class DuplicateAgentError(Exception):
    """Raised when duplicate agents are found in the configuration."""
    pass
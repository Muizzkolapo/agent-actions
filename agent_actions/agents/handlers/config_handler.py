"""Module for Configuration Validation Functions."""
import yaml
from pathlib import Path
from pydantic import ValidationError
from agent_actions.core.core_utils import Utils
from agent_actions.core.graph.render_workflow import render_pipeline_with_templates
from agent_actions.agents.validators.config_validator import ConfigValidator
from typing import Dict, Any, Optional, List
from agent_actions.cli.exceptions import ConfigurationError, TemplateRenderingError
from agent_actions.core.parser.config_schema import AgentConfig, DefaultAgentConfig
from agent_actions.core.context.environment_config import EnvironmentConfig
from agent_actions.core.parser.pipeline_config import WorkflowConfig, PipelineConfig
from agent_actions.core.context.path_config import load_project_config
from agent_actions.core.context.path_manager import PathManager
from agent_actions.core.parser.action_expander import ActionExpander



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
            raise ConfigurationError(f"Error rendering or loading user config from {self.constructor_path}: {e}") from e
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Error parsing YAML for user config from {self.constructor_path}: {e}") from e
        except Exception as e: # Catch other unexpected errors
            raise ConfigurationError(f"Unexpected error loading user config from {self.constructor_path}: {str(e)}") from e

        try:
            default_config_data = render_pipeline_with_templates(self.default_path, self.template_dir)
            self.default_config = yaml.safe_load(default_config_data)
        except (TemplateRenderingError, ConfigurationError) as e: # Catch specific errors from render_pipeline
            raise ConfigurationError(f"Error rendering or loading default config from {self.default_path}: {e}") from e
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Error parsing YAML for default config from {self.default_path}: {e}") from e
        except Exception as e: # Catch other unexpected errors
            raise ConfigurationError(f"Unexpected error loading default config from {self.default_path}: {str(e)}") from e

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
            error_msg = f"Top-level key '{self.agent_name}' does not match the filename '{config_filename}'"
            raise ValueError(error_msg)

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
                raise ConfigurationError(f"Invalid agent configuration: {e}") from e

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

        self.execution_order = Utils.topological_sort(dependency_graph)
    
    def load_environment_config(self) -> EnvironmentConfig:
        """Load and validate environment configuration."""
        try:
            self.environment_config = EnvironmentConfig()
            return self.environment_config
        except ValidationError as e:
            raise ConfigurationError(f"Invalid environment configuration: {e}") from e
    
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
            raise ConfigurationError(f"Invalid workflow configuration: {e}") from e
    
    def create_pipeline_config(self, pipeline_data: Dict[str, Any]) -> PipelineConfig:
        """Create a typed pipeline configuration from dictionary data."""
        try:
            self.pipeline_config = PipelineConfig.model_validate(pipeline_data)
            return self.pipeline_config
        except ValidationError as e:
            raise ConfigurationError(f"Invalid pipeline configuration: {e}") from e
    
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
                raise ConfigurationError(f"Agent '{agent_type}' configuration is invalid: {e}") from e
    
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


class DuplicateAgentError(Exception):
    """Raised when duplicate agents are found in the configuration."""
    pass
"""Module for Configuration Validation Functions."""
import yaml
from pathlib import Path
from pydantic import ValidationError
from agent_actions.core.utils import Utils
from agent_actions.workflow.render_workflow import render_pipeline_with_templates
from agent_actions.cli.validators.config_validator import ConfigValidator
from typing import Dict, Any
from agent_actions.cli.exceptions import ConfigurationError, TemplateRenderingError
from agent_actions.models.config_schema import AgentConfig, DefaultAgentConfig



class ConfigManager:
    def __init__(self, constructor_path, default_path):
        self.constructor_path = constructor_path
        self.default_path = default_path
        self.user_config = None
        self.default_config = None
        self.agent_name = None
        self.agent_configs = {}
        self.execution_order = []
        self.child_pipeline = None
        self.template_dir = str(Path.cwd() / "templates")

    def load_configs(self):
        try:
            config_data = render_pipeline_with_templates(self.constructor_path, self.template_dir)
            self.user_config = yaml.safe_load(config_data)
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

    def find_agent_name(self,config: Dict[str, Any]) -> str:
        """
        Find the name of the agent from the configuration.
        
        Args:
            config: Agent configuration dictionary
            
        Returns:
            str: Name of the agent
        """
        return next(iter(config)) 
    
    def validate_agent_name(self):
        self.agent_name = self.find_agent_name(self.user_config)
        config_filename = Path(self.constructor_path).stem
        if self.agent_name != config_filename:
            error_msg = f"Top-level key '{self.agent_name}' does not match the filename '{config_filename}'"
            raise ValueError(error_msg)

    def check_child_pipeline(self):
        for item in self.user_config[self.agent_name]:
            if isinstance(item, dict) and 'child' in item:
                self.child_pipeline = item['child'][0]
                return
        self.child_pipeline = None

    def get_user_agents(self):
        agents_section = self.user_config[self.agent_name]
        if 'agents' in agents_section:
            user_agents = agents_section['agents']
        else:
            user_agents = [agent for agent in agents_section if isinstance(agent, dict) and 'agent_type' in agent]
        return user_agents

    def merge_agent_configs(self, user_agents):
        default_model = DefaultAgentConfig.model_validate(
            self.default_config.get('default_agent_config', {})
        )
        default_agent_config = default_model.model_dump()

        for agent in user_agents:
            try:
                agent_model = AgentConfig.model_validate(agent)
            except ValidationError as e:
                raise ConfigurationError(f"Invalid agent configuration: {e}") from e

            agent_type = agent_model.agent_type
            merged_agent_config = {**default_agent_config, **agent_model.model_dump(exclude_unset=True)}
            self.agent_configs[agent_type] = merged_agent_config

    def determine_execution_order(self, user_agents):
        """
        Determines the execution order of agents based on their dependencies,
        considering only is_operational agents.
        """
        instance_config = ConfigValidator()
        instance_config.validate(self.agent_configs)
        
        dependency_graph = {}
        for agent_type, config in self.agent_configs.items():
            if config.get('is_operational', True):
                dependencies = [
                    dep for dep in config.get('dependencies', [])
                    if self.agent_configs[dep].get('is_operational', True)
                ]
                dependency_graph[agent_type] = dependencies

        self.execution_order = Utils.topological_sort(dependency_graph)

class DuplicateAgentError(Exception):
    """Raised when duplicate agents are found in the configuration."""
    pass
"""Module for Configuration Validation Functions."""
import os
import yaml
from agent_actions.core.utils import Utils
from agent_actions.workflow.render_workflow import render_pipeline_with_templates  
from agent_actions.cli.validators.config_validator import ConfigValidator  
from typing import Dict, Any, Union, List, Tuple, Optional, Set

import glob


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
        self.template_dir = os.path.join(os.getcwd(), "templates")

    def load_configs(self):
        try:
            config_data = render_pipeline_with_templates(self.constructor_path, self.template_dir)
            self.user_config = yaml.safe_load(config_data)
        except Exception as e:
            raise ValueError(f"Error loading config from {self.constructor_path}: {str(e)}")

        try:
            default_config_data = render_pipeline_with_templates(self.default_path, self.template_dir)
            self.default_config = yaml.safe_load(default_config_data)
        except Exception as e:
            raise ValueError(f"Error loading default config from {self.default_path}: {str(e)}")

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
        config_filename = os.path.splitext(os.path.basename(self.constructor_path))[0]
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
        default_agent_config = self.default_config['default_agent_config']
        for agent in user_agents:
            agent_type = agent.get('agent_type')
            if agent_type:
                merged_agent_config = default_agent_config.copy()
                merged_agent_config.update(agent)
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
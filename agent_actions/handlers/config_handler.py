"""Module for Configuration Validation Functions."""
import os
import logging
from agent_actions.handlers.file_handler import FileHandler

from agent_actions.logging_setup import setup_logging
logger = setup_logging()


class ConfigValidator:
    """
    A class for validating agent configurations.
    """

    @staticmethod
    def validate_agent_config(agent_config):
        """
        Validate the agent configuration to ensure all required fields are present and correctly formatted.
        """
        base_required_keys = {'agent_type', 'model_name'}
        tool_required_keys = {'description'}
        additional_required_keys = {'api_key', 'schema_name', 'prompt'}

        for idx, agent in enumerate(agent_config):
            # Determine the required keys based on the model_vendor
            if agent.get('model_vendor') == 'tool':
                required_keys = base_required_keys.union(tool_required_keys)
            else:
                required_keys = base_required_keys.union(additional_required_keys)

            missing_keys = required_keys - agent.keys()
            if missing_keys:
                return False, f"Agent {idx + 1} is missing required keys: {', '.join(missing_keys)}"

            # Ensure dependencies is a list if it exists, otherwise set it to an empty list
            if 'dependencies' in agent and not isinstance(agent['dependencies'], list):
                return False, f"Agent {idx + 1}: 'dependencies' should be a list."
            agent.setdefault('dependencies', [])

        return True, "Agent configuration is valid."

    @staticmethod
    def should_update_schema(agent_config, keys_list, side_collection):
        """
        Determines whether the schema should be updated based on the agent configuration.

        :param agent_config: Configuration dictionary for the agent
        :param keys_list: List of keys in the select list
        :param side_collection: Dictionary containing the select list
        :return: Boolean indicating whether the schema should be updated
        """
        return agent_config['agent_type'] == keys_list[0] and side_collection[agent_config['agent_type']]

    @staticmethod
    def check_agent_name_unique(agent_name, base_dir):
        """
        Check if the agent name is unique across the entire project.
        """
        all_agent_paths = FileHandler.get_all_agent_paths(base_dir)
        agent_names = [os.path.splitext(os.path.basename(path))[0] for path in all_agent_paths]
        return agent_names.count(agent_name) == 1

    @staticmethod
    def check_agent_file_unique(full_path, base_dir):
        """
        Check if the agent configuration file path is unique across the entire project.
        """
        all_agent_paths = FileHandler.get_all_agent_paths(base_dir)
        return all_agent_paths.count(full_path) == 1

    @staticmethod
    def find_agent_name(config):
        """
        Find the name of the agent from the configuration.
        """
        return next(iter(config))
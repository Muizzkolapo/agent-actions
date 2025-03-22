"""Module for Configuration Validation Functions."""
import os
from agent_actions.handlers.file_handler import FileHandler
import glob


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
    def validate_dependencies(agent_configs):
        """
        Validates that no active agent depends on an inactive agent.
        
        Args:
            agent_configs (dict): Dictionary of agent configurations
            
        Raises:
            ValueError: If an active agent depends on an inactive agent
        """
        active_agents = {
            agent_type for agent_type, config in agent_configs.items() 
            if config.get('is_operational', True)
        }
        inactive_agents = {
            agent_type for agent_type, config in agent_configs.items() 
            if not config.get('is_operational', True)
        }

        for agent_type, config in agent_configs.items():
            if agent_type in active_agents:
                dependencies = config.get('dependencies', [])
                for dep in dependencies:
                    if dep in inactive_agents:
                        raise ValueError(
                            f"Agent '{agent_type}' depends on inactive agent '{dep}'. "
                            f"Please either activate '{dep}' or remove it from the dependencies."
                        )
                    elif dep not in agent_configs:
                        raise ValueError(
                            f"Agent '{agent_type}' depends on non-existent agent '{dep}'. "
                            f"Please check your configuration."
                        )

    @staticmethod
    def should_update_schema(agent_config, keys_list, side_collection):
        """
        Determines whether the schema should be updated based on the agent configuration.
        """
        return (agent_config['agent_type'] == keys_list[0] and 
                bool(agent_config.get('side_collection')))

    @staticmethod
    def check_agent_name_unique(agent_name, base_dir):
        """
        Check if the agent name is unique across all agent_config folders in the project.
        Returns (bool, str): (is_unique, error_message if any)
        """
        def find_agent_config_dirs(start_path):
            agent_config_dirs = []
            for root, dirs, _ in os.walk(start_path):
                if "agent_config" in dirs:
                    agent_config_dirs.append(os.path.join(root, "agent_config"))
            return agent_config_dirs

        name_locations = {}
        duplicates = {}
        
        for config_dir in find_agent_config_dirs(base_dir):
            yaml_files = glob.glob(os.path.join(config_dir, "*.yaml"))
            yml_files = glob.glob(os.path.join(config_dir, "*.yml"))
            all_files = yaml_files + yml_files
            
            for file_path in all_files:
                name = os.path.splitext(os.path.basename(file_path))[0]
                
                if name in name_locations:
                    if name not in duplicates:
                        duplicates[name] = [name_locations[name]]
                    duplicates[name].append(file_path)
                else:
                    name_locations[name] = file_path

        if duplicates:
            error_msg = "ERROR: Duplicate agent configurations detected!\n"
            error_msg += "=" * 50 + "\n"
            for name, paths in duplicates.items():
                error_msg += f"\nAgent '{name}' is defined in multiple locations:\n"
                for i, path in enumerate(paths, 1):
                    rel_path = os.path.relpath(path, base_dir)
                    error_msg += f"{i}. {rel_path}\n"
                error_msg += "\nPlease remove duplicate configurations before proceeding."
            return False, error_msg

        return True, ""

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
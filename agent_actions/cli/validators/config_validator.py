import os
import glob
import logging
from typing import Dict, Any, List, Tuple, Optional, Set
from pathlib import Path

from agent_actions.cli.exceptions import ConfigurationError
from agent_actions.cli.utils.service_logger import ServiceLogger
from agent_actions.handlers.file_handler import FileHandler

import os
import logging
from pathlib import Path
from typing import Dict, Any, Union, List, Tuple, Optional, Set

from agent_actions.cli.exceptions import ConfigValidationError
from agent_actions.cli.validators.error_wrap import as_validation_error     # 🆕

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class ConfigurationValidator:
    @classmethod
    def validate_full_agent_config(cls, config: Dict[str, Any], agent_name: str) -> None:
        if agent_name not in config:
            raise ConfigValidationError(f"Agent '{agent_name}' not found in configuration.")
        agent_config = config[agent_name]
        cls.validate_agent_entries(agent_config, agent_name)
    """Handles configuration validation operations."""
    
    # List of required agent entry keys
    REQUIRED_AGENT_KEYS = {'agent_type', 'name'}
    
    # List of optional agent entry keys
    OPTIONAL_AGENT_KEYS = {'description', 'version', 'author', 'dependencies', 'imports', 'config', 'parent'}
    
    # Map of agent types to their specific required keys
    AGENT_TYPE_REQUIRED_KEYS = {
        'llm': {'model'},
        'function': {'code_path'},
        'tool': {'api_key'},
        # Add more as needed
    }
    
    @as_validation_error(ConfigValidationError)              
    def validate_agent_config(agent_name: str, config_path: Path, project_dir: Path) -> None:
        """
        Validate the agent configuration file.

        Args:
            agent_name: Name of the agent.
            config_path: Path to the agent configuration file.
            project_dir: Path to the project directory.
            
        Raises:
            ConfigValidationError: If configuration validation fails.
        """
        logger.info("Validating agent configuration", extra={
            'agent_name': agent_name,
            'config_path': str(config_path),
            'project_dir': str(project_dir)
        })
        
        try:
            # Check if the configuration file exists
            if not config_path.exists():
                raise ConfigValidationError(f"Configuration file does not exist: {config_path}")
                
            # Check if the file is readable
            if not os.access(config_path, os.R_OK):
                raise ConfigValidationError(f"Configuration file is not readable: {config_path}")
                
            # Check if the configuration file is unique
            is_unique = ConfigValidator.check_agent_file_unique(str(config_path), str(project_dir))
            if not is_unique:
                error_msg = f"Duplicate agent configuration file: {config_path}"
                logger.error(error_msg, extra={'agent_name': agent_name})
                raise ConfigValidationError(error_msg)

            # Check if the agent name is unique
            is_name_unique, error_msg = ConfigValidator.check_agent_name_unique(agent_name, str(project_dir))
            if not is_name_unique:
                logger.error(f"Agent name conflict: {error_msg}", extra={'agent_name': agent_name})
                raise ConfigValidationError(f"Agent name is not unique: {agent_name}. {error_msg}")

            logger.info("Agent configuration validation successful", extra={'agent_name': agent_name})
            
        except Exception as e:
            if isinstance(e, ConfigValidationError):
                raise
                
            logger.error(f"Configuration validation failed: {str(e)}", 
                        extra={'agent_name': agent_name}, exc_info=True)
            raise ConfigValidationError(f"Failed to validate agent configuration: {str(e)}") from e

    @classmethod
    def validate_agent_entries(cls, agent_config: Union[List[Dict[str, Any]], Any], agent_name: str) -> None:
        """
        Validate the agent entries in the configuration.

        Args:
            agent_config: Agent configuration data.
            agent_name: Name of the agent.
            
        Raises:
            ConfigValidationError: If agent entries validation fails.
        """
        logger.info("Validating agent entries", extra={'agent_name': agent_name})
        
        try:
            # Basic type validation
            if not isinstance(agent_config, list):
                error_msg = f"Agent configuration must be a list for {agent_name}, got {type(agent_config).__name__}"
                logger.error(error_msg, extra={'agent_name': agent_name})
                raise ConfigValidationError(error_msg)
                
            # Empty config check
            if not agent_config:
                error_msg = f"Agent configuration is empty for {agent_name}"
                logger.error(error_msg, extra={'agent_name': agent_name})
                raise ConfigValidationError(error_msg)
                
            # Extract agent entries (items with agent_type)
            agent_entries = []
            for i, entry in enumerate(agent_config):
                if not isinstance(entry, dict):
                    logger.warning(f"Non-dictionary entry at index {i} in agent config", 
                                 extra={'agent_name': agent_name})
                    continue
                    
                if 'agent_type' in entry:
                    agent_entries.append(entry)
                    
            # Check if any agent entries were found
            if not agent_entries:
                error_msg = f"No agent entries found in configuration for {agent_name}"
                logger.error(error_msg, extra={'agent_name': agent_name})
                raise ConfigValidationError(error_msg)
                
            # Validate each agent entry
            for i, entry in enumerate(agent_entries):
                cls._validate_agent_entry(entry, i, agent_name)
                
            # Use the base validator as an additional check
            is_valid, message = ConfigValidator.validate_agent_config(agent_entries)
            if not is_valid:
                logger.error(f"Invalid agent configuration: {message}", 
                           extra={'agent_name': agent_name})
                raise ConfigValidationError(f"Invalid agent configuration for {agent_name}: {message}")

            logger.info("Agent entries validation successful", extra={'agent_name': agent_name})
            
        except Exception as e:
            if isinstance(e, ConfigValidationError):
                raise
                
            logger.error(f"Agent entries validation failed: {str(e)}", 
                        extra={'agent_name': agent_name}, exc_info=True)
            raise ConfigValidationError(f"Failed to validate agent entries: {str(e)}") from e
    
    @classmethod
    def _validate_agent_entry(cls, entry: Dict[str, Any], index: int, agent_name: str) -> None:
        """
        Validate a single agent entry in the configuration.
        
        Args:
            entry: Agent entry to validate.
            index: Index of the entry for error reporting.
            agent_name: Name of the agent for error reporting.
            
        Raises:
            ConfigValidationError: If the agent entry is invalid.
        """
        agent_type = entry.get('agent_type') 
        # Check required keys
        # Check if name matches agent_name
        # Check agent type specific required keys
        # Check for unknown keys
        # Validate types of common fields
        if 'description' in entry and not isinstance(entry['description'], str):
            error_msg = (f"Agent entry at index {index} for {agent_name} has invalid "
                        f"description type: {type(entry['description']).__name__}, expected string")
            logger.error(error_msg)
            raise ConfigValidationError(error_msg)
            
        if 'version' in entry and not isinstance(entry['version'], (str, int, float)):
            error_msg = (f"Agent entry at index {index} for {agent_name} has invalid "
                        f"version type: {type(entry['version']).__name__}, expected string or number")
            logger.error(error_msg)
            raise ConfigValidationError(error_msg)
            
        if 'dependencies' in entry and not isinstance(entry['dependencies'], list):
            error_msg = (f"Agent entry at index {index} for {agent_name} has invalid "
                        f"dependencies type: {type(entry['dependencies']).__name__}, expected list")
            logger.error(error_msg)
            raise ConfigValidationError(error_msg)
            
        # Type-specific validations
        if agent_type == 'llm' and 'model' in entry:
            if not isinstance(entry['model'], str):
                error_msg = (f"Agent entry at index {index} of type 'llm' for {agent_name} "
                            f"has invalid model type: {type(entry['model']).__name__}, expected string")
                logger.error(error_msg)
                raise ConfigValidationError(error_msg)
                
        if agent_type == 'function' and 'code_path' in entry:
            if not isinstance(entry['code_path'], str):
                error_msg = (f"Agent entry at index {index} of type 'function' for {agent_name} "
                            f"has invalid code_path type: {type(entry['code_path']).__name__}, expected string")
                logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            
            # Validate code path exists if it's a relative path
            code_path = entry['code_path']
            if not code_path.startswith(('http://', 'https://')):
                code_file = Path(code_path)
                if not code_file.is_absolute():
                    # Relative path, should be relative to project root
                    project_root = Path.cwd()
                    code_file = project_root / code_file
                    
                if not code_file.exists():
                    error_msg = (f"Agent entry at index {index} of type 'function' for {agent_name} "
                                f"has code_path that does not exist: {code_path}")
                    logger.error(error_msg)
                    raise ConfigValidationError(error_msg)
    
    @classmethod
    def validate_config_dependencies(cls, config: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        """
        Validate that all dependencies in a configuration exist.
        
        Args:
            config: Full configuration with all agents.
            
        Returns:
            List of error messages for missing dependencies.
        """
        errors = []
        available_agents = set(config.keys())
        
        for agent_name, agent_entries in config.items():
            # Skip if not a list (shouldn't happen with validated config)
            if not isinstance(agent_entries, list):
                continue
                
            dependencies = set()
            
            # Extract all dependencies from agent entries
            for entry in agent_entries:
                if not isinstance(entry, dict):
                    continue
                    
                # Direct dependencies
                if 'dependencies' in entry and isinstance(entry['dependencies'], list):
                    dependencies.update([
                        dep for dep in entry['dependencies']
                        if isinstance(dep, str)
                    ])
                
                # Imported dependencies
                if 'imports' in entry and isinstance(entry['imports'], list):
                    for imp in entry['imports']:
                        if isinstance(imp, str):
                            dependencies.add(imp)
                        elif isinstance(imp, dict) and 'name' in imp:
                            imp_name = imp.get('name')
                            if isinstance(imp_name, str):
                                dependencies.add(imp_name)
                
                # Parent dependencies
                if 'parent' in entry and isinstance(entry['parent'], list):
                    dependencies.update([
                        parent for parent in entry['parent']
                        if isinstance(parent, str)
                    ])
            
            # Check that all dependencies exist
            missing_deps = dependencies - available_agents
            if missing_deps:
                deps_list = ", ".join(missing_deps)
                errors.append(f"Agent '{agent_name}' has missing dependencies: {deps_list}")
                
        return errors
    
    @classmethod
    def check_circular_dependencies(cls, config: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        """
        Check for circular dependencies in the configuration.
        
        Args:
            config: Full configuration with all agents.
            
        Returns:
            List of error messages for circular dependencies.
        """
        # Build dependency graph
        graph = {}
        for agent_name, agent_entries in config.items():
            # Initialize empty dependency list
            graph[agent_name] = []
            
            # Skip if not a list
            if not isinstance(agent_entries, list):
                continue
                
            # Extract dependencies
            for entry in agent_entries:
                if not isinstance(entry, dict):
                    continue
                    
                # Direct dependencies
                if 'dependencies' in entry and isinstance(entry['dependencies'], list):
                    graph[agent_name].extend([
                        dep for dep in entry['dependencies']
                        if isinstance(dep, str)
                    ])
                
                # Imported dependencies
                if 'imports' in entry and isinstance(entry['imports'], list):
                    for imp in entry['imports']:
                        if isinstance(imp, str):
                            graph[agent_name].append(imp)
                        elif isinstance(imp, dict) and 'name' in imp:
                            imp_name = imp.get('name')
                            if isinstance(imp_name, str):
                                graph[agent_name].append(imp_name)
                
                # Parent dependencies
                if 'parent' in entry and isinstance(entry['parent'], list):
                    graph[agent_name].extend([
                        parent for parent in entry['parent']
                        if isinstance(parent, str)
                    ])
            
            # Remove duplicates
            graph[agent_name] = list(set(graph[agent_name]))
        
        # Detect cycles using DFS
        errors = []
        visited = set()
        path = []
        
        def dfs(node):
            if node in path:
                # Circular dependency found
                cycle = ' -> '.join(path[path.index(node):] + [node])
                errors.append(f"Circular dependency detected: {cycle}")
                return
                
            if node in visited:
                return
                
            visited.add(node)
            path.append(node)
            
            for neighbor in graph.get(node, []):
                dfs(neighbor)
                
            path.pop()
            
        for node in graph:
            if node not in visited:
                dfs(node)
                
        return errors
    


class ConfigValidator:
    """Utility class for validating configuration data."""
    
    @staticmethod
    def validate_list_config(config: Any, config_name: str = "configuration") -> None:
        """
        Validate that a configuration is a list.
        
        Args:
            config: Configuration to validate.
            config_name: Name of the configuration for error messages.
            
        Raises:
            ConfigurationError: If validation fails.
        """
        try:
            ServiceLogger.log_operation_start(logger, "validate list config", 
                                           config_name=config_name)
            
            if not isinstance(config, list):
                error_msg = f"{config_name} must be a list, got {type(config)}"
                logger.error(error_msg)
                raise ConfigurationError(error_msg)
                
            ServiceLogger.log_operation_success(logger, "validate list config", 
                                             config_name=config_name)
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "validate list config", e)
            raise
            
    @staticmethod
    def validate_agent_config(agent_config: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Validate the agent configuration to ensure all required fields are present and correctly formatted.
        
        Args:
            agent_config: List of agent configurations to validate.
            
        Returns:
            Tuple of (bool, str): (is_valid, error_message if any)
        """
        try:
            ServiceLogger.log_operation_start(logger, "validate agent config")
            
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
                    error_msg = f"Agent {idx + 1} is missing required keys: {', '.join(missing_keys)}"
                    ServiceLogger.log_operation_error(logger, "validate agent config", 
                                                   error_msg=error_msg)
                    return False, error_msg

                # Ensure dependencies is a list if it exists, otherwise set it to an empty list
                if 'dependencies' in agent and not isinstance(agent['dependencies'], list):
                    error_msg = f"Agent {idx + 1}: 'dependencies' should be a list."
                    ServiceLogger.log_operation_error(logger, "validate agent config", 
                                                   error_msg=error_msg)
                    return False, error_msg
                agent.setdefault('dependencies', [])

            ServiceLogger.log_operation_success(logger, "validate agent config")
            return True, "Agent configuration is valid."
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "validate agent config", e)
            raise
            
    @staticmethod
    def validate_dependencies(agent_configs: Dict[str, Dict[str, Any]]) -> None:
        """
        Validates that no active agent depends on an inactive agent.
        
        Args:
            agent_configs: Dictionary of agent configurations
            
        Raises:
            ConfigurationError: If an active agent depends on an inactive agent
        """
        try:
            ServiceLogger.log_operation_start(logger, "validate dependencies")
            
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
                            error_msg = (
                                f"Agent '{agent_type}' depends on inactive agent '{dep}'. "
                                f"Please either activate '{dep}' or remove it from the dependencies."
                            )
                            ServiceLogger.log_operation_error(logger, "validate dependencies", 
                                                           error_msg=error_msg)
                            raise ConfigurationError(error_msg)
                        elif dep not in agent_configs:
                            error_msg = (
                                f"Agent '{agent_type}' depends on non-existent agent '{dep}'. "
                                f"Please check your configuration."
                            )
                            ServiceLogger.log_operation_error(logger, "validate dependencies", 
                                                           error_msg=error_msg)
                            raise ConfigurationError(error_msg)
                            
            ServiceLogger.log_operation_success(logger, "validate dependencies")
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "validate dependencies", e)
            raise
            
    @staticmethod
    def should_update_schema(agent_config: Dict[str, Any], keys_list: List[str], 
                           side_collection: Any) -> bool:
        """
        Determines whether the schema should be updated based on the agent configuration.
        
        Args:
            agent_config: Agent configuration dictionary
            keys_list: List of keys to check
            side_collection: Side collection to check
            
        Returns:
            bool: Whether the schema should be updated
        """
        return (agent_config['agent_type'] == keys_list[0] and 
                bool(agent_config.get('side_collection')))
                
    @staticmethod
    def check_agent_name_unique(agent_name: str, base_dir: str) -> Tuple[bool, str]:
        """
        Check if the agent name is unique across all agent_config folders in the project.
        
        Args:
            agent_name: Name of the agent to check
            base_dir: Base directory to start searching from
            
        Returns:
            Tuple of (bool, str): (is_unique, error_message if any)
        """
        try:
            ServiceLogger.log_operation_start(logger, "check agent name unique", 
                                           agent_name=agent_name)
            
            def find_agent_config_dirs(start_path: str) -> List[str]:
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
                ServiceLogger.log_operation_error(logger, "check agent name unique", 
                                               error_msg=error_msg)
                return False, error_msg

            ServiceLogger.log_operation_success(logger, "check agent name unique", 
                                             agent_name=agent_name)
            return True, ""
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "check agent name unique", e)
            raise
            
    @staticmethod
    def check_agent_file_unique(full_path: str, base_dir: str) -> bool:
        """
        Check if the agent configuration file path is unique across the entire project.
        
        Args:
            full_path: Full path to the agent configuration file
            base_dir: Base directory to start searching from
            
        Returns:
            bool: Whether the file path is unique
        """
        try:
            ServiceLogger.log_operation_start(logger, "check agent file unique", 
                                           full_path=full_path)
            
            all_agent_paths = FileHandler.get_all_agent_paths(base_dir)
            is_unique = all_agent_paths.count(full_path) == 1
            
            ServiceLogger.log_operation_success(logger, "check agent file unique", 
                                             is_unique=is_unique)
            return is_unique
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "check agent file unique", e)
            raise
            
    @staticmethod
    def find_agent_name(config: Dict[str, Any]) -> str:
        """
        Find the name of the agent from the configuration.
        
        Args:
            config: Agent configuration dictionary
            
        Returns:
            str: Name of the agent
        """
        return next(iter(config)) 
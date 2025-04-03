"""
Configuration validation utilities.

This module provides utilities for validating agent configurations
and ensuring they meet the required format and constraints.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Union, List, Tuple, Optional, Set

from agent_actions.handlers.config_handler import ConfigValidator as BaseConfigValidator
from agent_actions.cli.exceptions import ConfigValidationError
logger = logging.getLogger(__name__)


class ConfigurationValidator:
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
    
    @staticmethod
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
            is_unique = BaseConfigValidator.check_agent_file_unique(str(config_path), str(project_dir))
            if not is_unique:
                error_msg = f"Duplicate agent configuration file: {config_path}"
                logger.error(error_msg, extra={'agent_name': agent_name})
                raise ConfigValidationError(error_msg)

            # Check if the agent name is unique
            is_name_unique, error_msg = BaseConfigValidator.check_agent_name_unique(agent_name, str(project_dir))
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
            is_valid, message = BaseConfigValidator.validate_agent_config(agent_entries)
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
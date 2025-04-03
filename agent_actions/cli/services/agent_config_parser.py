"""
Agent configuration parsing service.

This module provides services for parsing and extracting information
from agent configuration files.
"""

import logging
from typing import Dict, Any, List, Optional, Union, Set

from agent_actions.cli.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class AgentConfigParser:
    """Handles agent configuration parsing operations."""
    
    @staticmethod
    def get_parent_pipeline(agent_config: List[Dict[str, Any]]) -> Optional[str]:
        """
        Get the parent pipeline from the agent configuration.

        Args:
            agent_config: Agent configuration data.

        Returns:
            Parent pipeline name if found, None otherwise.
            
        Raises:
            ConfigurationError: If the configuration format is invalid or cannot be parsed.
        """
        logger.debug("Starting parent pipeline extraction from agent config")
        
        # Basic validation
        if not isinstance(agent_config, list):
            raise ConfigurationError("Agent configuration must be a list")
        
        try:
            for item in agent_config:
                if not isinstance(item, dict):
                    logger.warning("Non-dictionary item found in agent configuration")
                    continue
                    
                if 'parent' in item:
                    parent_list = item.get('parent')
                    
                    if parent_list is None:
                        logger.warning("Empty parent field found in configuration")
                        continue
                        
                    if not isinstance(parent_list, list):
                        logger.warning(f"Parent field is not a list: {type(parent_list)}")
                        continue
                        
                    if not parent_list:
                        logger.warning("Parent list is empty")
                        continue
                        
                    parent = parent_list[0]
                    if not isinstance(parent, str):
                        logger.warning(f"Parent is not a string: {type(parent)}")
                        continue
                        
                    logger.debug(f"Found parent pipeline: {parent}")
                    return parent
                    
            logger.debug("No parent pipeline found in configuration")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing parent pipeline from config: {str(e)}")
            raise ConfigurationError(f"Failed to parse parent pipeline: {str(e)}") from e
    
    @staticmethod
    def get_agent_type(agent_config: List[Dict[str, Any]]) -> Optional[str]:
        """
        Get the agent type from the agent configuration.

        Args:
            agent_config: Agent configuration data.

        Returns:
            Agent type if found, None otherwise.
            
        Raises:
            ConfigurationError: If the configuration format is invalid or cannot be parsed.
        """
        logger.debug("Starting agent type extraction from agent config")
        
        # Basic validation
        if not isinstance(agent_config, list):
            raise ConfigurationError("Agent configuration must be a list")
        
        try:
            for item in agent_config:
                if not isinstance(item, dict):
                    continue
                    
                if 'agent_type' in item:
                    agent_type = item.get('agent_type')
                    
                    if not isinstance(agent_type, str):
                        logger.warning(f"Agent type is not a string: {type(agent_type)}")
                        continue
                        
                    logger.debug(f"Found agent type: {agent_type}")
                    return agent_type
                    
            logger.debug("No agent type found in configuration")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing agent type from config: {str(e)}")
            raise ConfigurationError(f"Failed to parse agent type: {str(e)}") from e
    
    @staticmethod
    def get_dependencies(agent_config: List[Dict[str, Any]]) -> Set[str]:
        """
        Get the dependencies from the agent configuration.

        Args:
            agent_config: Agent configuration data.

        Returns:
            Set of dependency names.
            
        Raises:
            ConfigurationError: If the configuration format is invalid or cannot be parsed.
        """
        logger.debug("Starting dependencies extraction from agent config")
        
        # Basic validation
        if not isinstance(agent_config, list):
            raise ConfigurationError("Agent configuration must be a list")
        
        dependencies = set()
        
        try:
            for item in agent_config:
                if not isinstance(item, dict):
                    continue
                    
                # Check 'dependencies' field
                if 'dependencies' in item:
                    deps_list = item.get('dependencies')
                    
                    if not isinstance(deps_list, list):
                        logger.warning(f"Dependencies field is not a list: {type(deps_list)}")
                        continue
                        
                    for dep in deps_list:
                        if isinstance(dep, str):
                            dependencies.add(dep)
                        else:
                            logger.warning(f"Dependency is not a string: {type(dep)}")
                
                # Check 'imports' field
                if 'imports' in item:
                    imports_list = item.get('imports')
                    
                    if not isinstance(imports_list, list):
                        logger.warning(f"Imports field is not a list: {type(imports_list)}")
                        continue
                        
                    for imp in imports_list:
                        if isinstance(imp, str):
                            dependencies.add(imp)
                        elif isinstance(imp, dict) and 'name' in imp:
                            imp_name = imp.get('name')
                            if isinstance(imp_name, str):
                                dependencies.add(imp_name)
                        else:
                            logger.warning(f"Import is not a string or valid import object: {imp}")
                    
            logger.debug(f"Found dependencies: {dependencies}")
            return dependencies
            
        except Exception as e:
            logger.error(f"Error parsing dependencies from config: {str(e)}")
            raise ConfigurationError(f"Failed to parse dependencies: {str(e)}") from e
    
    @staticmethod
    def validate_configuration_format(agent_config: Any) -> bool:
        """
        Validate the basic format of the agent configuration.

        Args:
            agent_config: Agent configuration data to validate.

        Returns:
            True if the format is valid, False otherwise.
            
        Raises:
            ConfigurationError: If there's a severe format issue.
        """
        logger.debug("Validating agent configuration format")
        
        # Check if it's a list
        if not isinstance(agent_config, list):
            error_msg = f"Agent configuration must be a list, got {type(agent_config)}"
            logger.error(error_msg)
            raise ConfigurationError(error_msg)
        
        # Check if it's empty
        if not agent_config:
            logger.warning("Agent configuration is empty")
            return False
        
        # Check if items are dictionaries
        for i, item in enumerate(agent_config):
            if not isinstance(item, dict):
                logger.warning(f"Item at index {i} is not a dictionary: {type(item)}")
                return False
        
        return True
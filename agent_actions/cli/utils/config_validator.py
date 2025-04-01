"""
Configuration validation utilities.

This module provides common utilities for validating configuration data.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Union

from agent_actions.cli.exceptions import ConfigurationError
from agent_actions.cli.utils.service_logger import ServiceLogger

logger = logging.getLogger(__name__)


class ConfigValidator:
    """Utility class for validating configuration data."""
    
    @staticmethod
    def validate_list_config(config: Any, config_name: str = "configuration") -> List[Dict[str, Any]]:
        """
        Validate that configuration is a list of dictionaries.
        
        Args:
            config: Configuration data to validate.
            config_name: Name of the configuration (for error messages).
            
        Returns:
            Validated configuration as a list of dictionaries.
            
        Raises:
            ConfigurationError: If the configuration format is invalid.
        """
        ServiceLogger.log_validation_start(logger, config_name)
        
        if not isinstance(config, list):
            error_msg = f"{config_name} must be a list, got {type(config)}"
            logger.error(error_msg)
            raise ConfigurationError(error_msg)
        
        if not config:
            logger.warning(f"{config_name} is empty")
            ServiceLogger.log_validation_success(logger, config_name)
            return []
        
        validated_config = []
        for i, item in enumerate(config):
            if not isinstance(item, dict):
                logger.warning(f"Item at index {i} in {config_name} is not a dictionary: {type(item)}")
                continue
            validated_config.append(item)
        
        ServiceLogger.log_validation_success(logger, config_name)
        return validated_config
    
    @staticmethod
    def validate_agent_config(config_data: List[Dict[str, Any]]) -> None:
        """
        Validate the format of an agent configuration.
        
        Args:
            config_data: List of configuration dictionaries.
            
        Raises:
            ConfigurationError: If the configuration format is invalid.
        """
        try:
            ServiceLogger.log_validation_start(logger, "agent configuration")
            
            # Validate basic list format
            ConfigValidator.validate_list_config(config_data, "agent configuration")
            
            # Additional agent-specific validation can be added here
            # For example, checking for required fields, valid values, etc.
            
            ServiceLogger.log_validation_success(logger, "agent configuration")
            
        except Exception as e:
            ServiceLogger.log_validation_error(logger, "agent configuration", e)
            raise
    
    @staticmethod
    def get_optional_string_field(
        config: List[Dict[str, Any]],
        field_name: str,
        config_name: str = "configuration"
    ) -> Optional[str]:
        """
        Get an optional string field from configuration.
        
        Args:
            config: Configuration data.
            field_name: Name of the field to get.
            config_name: Name of the configuration (for error messages).
            
        Returns:
            Field value if found and valid, None otherwise.
            
        Raises:
            ConfigurationError: If there's a severe format issue.
        """
        logger.debug(f"Extracting {field_name} from {config_name}")
        
        validated_config = ConfigValidator.validate_list_config(config, config_name)
        
        for item in validated_config:
            if field_name in item:
                field_value = item.get(field_name)
                
                if not isinstance(field_value, str):
                    logger.warning(f"{field_name} is not a string: {type(field_value)}")
                    continue
                    
                logger.debug(f"Found {field_name}: {field_value}")
                return field_value
                
        logger.debug(f"No {field_name} found in configuration")
        return None
    
    @staticmethod
    def get_optional_list_field(
        config: List[Dict[str, Any]],
        field_name: str,
        config_name: str = "configuration"
    ) -> List[str]:
        """
        Get an optional list field from configuration.
        
        Args:
            config: Configuration data.
            field_name: Name of the field to get.
            config_name: Name of the configuration (for error messages).
            
        Returns:
            List of string values if found and valid, empty list otherwise.
            
        Raises:
            ConfigurationError: If there's a severe format issue.
        """
        logger.debug(f"Extracting {field_name} from {config_name}")
        
        validated_config = ConfigValidator.validate_list_config(config, config_name)
        result = []
        
        for item in validated_config:
            if field_name in item:
                field_value = item.get(field_name)
                
                if not isinstance(field_value, list):
                    logger.warning(f"{field_name} is not a list: {type(field_value)}")
                    continue
                    
                for value in field_value:
                    if isinstance(value, str):
                        result.append(value)
                    else:
                        logger.warning(f"Item in {field_name} is not a string: {type(value)}")
                        
        logger.debug(f"Found {field_name}: {result}")
        return result
    
    @staticmethod
    def get_optional_dict_field(
        config: List[Dict[str, Any]],
        field_name: str,
        config_name: str = "configuration"
    ) -> List[Dict[str, Any]]:
        """
        Get an optional dictionary field from configuration.
        
        Args:
            config: Configuration data.
            field_name: Name of the field to get.
            config_name: Name of the configuration (for error messages).
            
        Returns:
            List of dictionary values if found and valid, empty list otherwise.
            
        Raises:
            ConfigurationError: If there's a severe format issue.
        """
        logger.debug(f"Extracting {field_name} from {config_name}")
        
        validated_config = ConfigValidator.validate_list_config(config, config_name)
        result = []
        
        for item in validated_config:
            if field_name in item:
                field_value = item.get(field_name)
                
                if not isinstance(field_value, list):
                    logger.warning(f"{field_name} is not a list: {type(field_value)}")
                    continue
                    
                for value in field_value:
                    if isinstance(value, dict):
                        result.append(value)
                    else:
                        logger.warning(f"Item in {field_name} is not a dictionary: {type(value)}")
                        
        logger.debug(f"Found {field_name}: {result}")
        return result
    
    @staticmethod
    def validate_required_fields(
        config: Dict[str, Any],
        required_fields: List[str],
        config_name: str = "configuration"
    ) -> None:
        """
        Validate that all required fields are present in a configuration dictionary.
        
        Args:
            config: Configuration dictionary to validate.
            required_fields: List of required field names.
            config_name: Name of the configuration (for error messages).
            
        Raises:
            ConfigurationError: If any required field is missing.
        """
        ServiceLogger.log_validation_start(logger, f"required fields in {config_name}")
        
        missing_fields = [field for field in required_fields if field not in config]
        
        if missing_fields:
            error_msg = f"Missing required fields in {config_name}: {', '.join(missing_fields)}"
            logger.error(error_msg)
            raise ConfigurationError(error_msg)
            
        ServiceLogger.log_validation_success(logger, f"required fields in {config_name}") 
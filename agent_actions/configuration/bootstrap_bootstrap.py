"""
Bootstrap module for initializing the application with dependency injection.

This module provides functions to set up the application container and integrate
with existing workflows while maintaining backward compatibility.
"""
import logging
from typing import Dict, Any, Optional
from contextlib import contextmanager
from agent_actions.orchestration.application_container import ApplicationContainer
from agent_actions.orchestration.agent_runner import AgentRunner
from .startup_validator import validate_startup, StartupValidationError
from agent_actions.state_management.environment_config import EnvironmentConfig
logger = logging.getLogger(__name__)

def initialize_application(constructor_path: Optional[str]=None, default_path: Optional[str]=None, skip_validation: bool=False) -> EnvironmentConfig:
    """
    Initialize the application with full startup validation.
    
    Args:
        constructor_path: Path to user configuration file
        default_path: Path to default configuration file  
        skip_validation: Skip startup validation (not recommended for production)
        
    Returns:
        EnvironmentConfig: Validated environment configuration
        
    Raises:
        StartupValidationError: If validation fails
    """
    logger.info('Initializing Agent Actions application...')
    if not skip_validation:
        try:
            env_config = validate_startup(constructor_path, default_path)
            logger.info('Application initialization completed successfully')
            return env_config
        except StartupValidationError as e:
            logger.error(f'Application initialization failed: {e}')
            logger.error('Validation errors:')
            for error in e.errors:
                logger.error(f'  - {error}')
            raise
    else:
        logger.warning('Startup validation skipped - this is not recommended for production')
        return EnvironmentConfig()

@contextmanager
def application_container_context(config: Optional[Dict[str, Any]]=None, validate_startup_config: bool=True, constructor_path: Optional[str]=None, default_path: Optional[str]=None):
    """
    Context manager for proper DI container lifecycle management.
    
    Args:
        config: Optional configuration dictionary. Uses development profile if not provided.
        validate_startup_config: Whether to run startup validation
        constructor_path: Path to user configuration file for context-aware validation
        default_path: Path to default configuration file
        
    Yields:
        ApplicationContainer instance
        
    Example:
        with application_container_context() as container:
            agent_runner = container.get_agent_runner()
    """
    if validate_startup_config and config is None:
        try:
            initialize_application(constructor_path, default_path)
        except StartupValidationError as e:
            logger.warning(
                f'Startup validation failed, continuing with default configuration: {e}',
                exc_info=True
            )
            logger.debug(f'Validation errors: {e.errors if hasattr(e, "errors") else "unknown"}')
    if config is None:
        container = ApplicationContainer.create_for_environment('development')
    else:
        container = ApplicationContainer(config)
    try:
        yield container
    finally:
        pass

def create_agent_runner(config: Optional[Dict[str, Any]]=None, use_tools: bool=True, constructor_path: Optional[str]=None, default_path: Optional[str]=None) -> AgentRunner:
    """
    Create an AgentRunner with proper dependency injection.
    
    Args:
        config: Optional configuration dictionary
        use_tools: Whether the agent runner should use tools
        constructor_path: Path to user configuration file for context-aware validation
        default_path: Path to default configuration file
        
    Returns:
        AgentRunner configured with DI
    """
    with application_container_context(config, validate_startup_config=True, constructor_path=constructor_path, default_path=default_path) as container:
        return container.get_agent_runner(use_tools)

def create_target_content_processor(config: Optional[Dict[str, Any]]=None, agent_config: Dict=None, agent_name: str=None, idx: int=None, agent_configs: Optional[Dict[str, Dict]]=None):
    """
    Create a TargetContentProcessor with proper dependency injection.

    Args:
        config: Optional DI configuration dictionary
        agent_config: Configuration for the agent
        agent_name: Name of the agent
        idx: Index of the config being processed
        agent_configs: Optional dict mapping agent names to their configs (for dependency resolution)

    Returns:
        TargetContentProcessor instance with injected dependencies
    """
    with application_container_context(config) as container:
        return container.create_target_content_processor(agent_config, agent_name, idx, agent_configs)
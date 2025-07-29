"""
Bootstrap module for initializing the application with dependency injection.

This module provides functions to set up the application container and integrate
with existing workflows while maintaining backward compatibility.
"""

from typing import Dict, Any, Optional
from .core.application_container import ApplicationContainer
from .core.agent_runner import AgentRunner


# Global application container instance
_app_container: Optional[ApplicationContainer] = None


def initialize_application(config: Optional[Dict[str, Any]] = None) -> ApplicationContainer:
    """
    Initialize the application with dependency injection.
    
    Args:
        config: Optional configuration dictionary. Uses development profile if not provided.
        
    Returns:
        ApplicationContainer instance
    """
    global _app_container
    
    if config is None:
        # Use development profile by default
        _app_container = ApplicationContainer.create_for_environment('development')
    else:
        _app_container = ApplicationContainer(config)
    
    return _app_container


def get_application_container() -> ApplicationContainer:
    """
    Get the global application container.
    
    Returns:
        ApplicationContainer instance
        
    Raises:
        RuntimeError: If application has not been initialized
    """
    global _app_container
    
    if _app_container is None:
        # Auto-initialize with development settings
        _app_container = initialize_application()
    
    return _app_container


def create_agent_runner(use_tools: bool = True) -> AgentRunner:
    """
    Create an AgentRunner with dependency injection support.
    
    Args:
        use_tools: Whether the agent runner should use tools
        
    Returns:
        AgentRunner configured with DI
    """
    container = get_application_container()
    return container.get_agent_runner(use_tools)


def reset_application():
    """
    Reset the global application container.
    
    This is primarily useful for testing scenarios where you need
    to start with a clean container.
    """
    global _app_container
    _app_container = None


# Convenience functions for backward compatibility
def get_agent_runner_with_di(use_tools: bool = True) -> AgentRunner:
    """
    Backward compatibility function for getting an AgentRunner with DI.
    
    Args:
        use_tools: Whether the agent runner should use tools
        
    Returns:
        AgentRunner configured with DI
    """
    return create_agent_runner(use_tools)


def is_di_enabled() -> bool:
    """
    Check if dependency injection is enabled.
    
    Returns:
        True if DI container is initialized, False otherwise
    """
    global _app_container
    return _app_container is not None
# pylint: disable=duplicate-code
"""
Bootstrap factory for initializing the application with dependency injection.

This module provides functions to set up the application container and integrate
with existing workflows while maintaining backward compatibility.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, Optional

from agent_actions.orchestration.agent_runner import AgentRunner
from agent_actions.orchestration.application_container import ApplicationContainer

logger = logging.getLogger(__name__)


@contextmanager
def application_container_context(config: Optional[Dict[str, Any]] = None):
    """
    Context manager for proper DI container lifecycle management.

    Args:
        config: Optional configuration dictionary. Uses development profile if not provided.

    Yields:
        ApplicationContainer instance

    Example:
        with application_container_context() as container:
            agent_runner = container.get_agent_runner()
    """
    if config is None:
        container = ApplicationContainer.create_for_environment('development')
    else:
        container = ApplicationContainer(config)

    try:
        yield container
    finally:
        # Container cleanup would go here if needed
        pass


def create_agent_runner(
    config: Optional[Dict[str, Any]] = None,
    use_tools: bool = True,
    constructor_path: Optional[str] = None,  # pylint: disable=unused-argument
    default_path: Optional[str] = None  # pylint: disable=unused-argument
) -> AgentRunner:
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
    with application_container_context(config) as container:
        return container.get_agent_runner(use_tools)


def create_target_content_processor(
    config: Optional[Dict[str, Any]] = None,
    agent_config: Dict = None,
    agent_name: str = None,
    idx: int = None,
    agent_configs: Optional[Dict[str, Dict]] = None
):
    """
    Create a TargetContentProcessor with proper dependency injection.

    Args:
        config: Optional DI configuration dictionary
        agent_config: Configuration for the agent
        agent_name: Name of the agent
        idx: Index of the config being processed
        agent_configs: Optional dictionary of all agent configurations

    Returns:
        TargetContentProcessor instance with injected dependencies
    """
    with application_container_context(config) as container:
        return container.create_target_content_processor(
            agent_config, agent_name, idx, agent_configs
        )

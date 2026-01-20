"""
Factory module for creating components with dependency injection.

Provides factory functions to create AgentRunner
instances with proper DI container lifecycle management.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, Optional

from agent_actions.workflow.runner import AgentRunner
from agent_actions.config.di.application import ApplicationContainer

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
        container = ApplicationContainer.create_for_environment("development")
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
    constructor_path: Optional[str] = None,
    default_path: Optional[str] = None,
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

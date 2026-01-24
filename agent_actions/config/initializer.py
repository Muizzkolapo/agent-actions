"""
Application initializer with startup validation.

Provides functions to set up the application container with full validation,
including environment config and dependency injection setup.
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from agent_actions.workflow.runner import AgentRunner
from agent_actions.config.di.application import ApplicationContainer
from agent_actions.config.environment import EnvironmentConfig

from agent_actions.validation.startup import StartupValidationError, validate_startup
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    ApplicationInitializationStartEvent,
    StartupValidationStartEvent,
    StartupValidationCompleteEvent,
    DIContainerInitializationEvent,
)

logger = logging.getLogger(__name__)


def initialize_application(
    constructor_path: Optional[str] = None,
    default_path: Optional[str] = None,
    skip_validation: bool = False,
) -> EnvironmentConfig:
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
    fire_event(ApplicationInitializationStartEvent())
    logger.info("Initializing Agent Actions application...")
    if not skip_validation:
        try:
            fire_event(StartupValidationStartEvent())
            start_time = datetime.now()
            env_config = validate_startup(constructor_path, default_path)
            elapsed_time = (datetime.now() - start_time).total_seconds()
            fire_event(StartupValidationCompleteEvent(elapsed_time=elapsed_time))
            logger.info("Application initialization completed successfully")
            return env_config
        except StartupValidationError as e:
            logger.error("Application initialization failed: %s", e)
            logger.error("Validation errors:")
            for error in e.errors:
                logger.error("  - %s", error)
            raise
    else:
        logger.warning("Startup validation skipped - this is not recommended for production")
        return EnvironmentConfig()


@contextmanager
def application_container_context(
    config: Optional[Dict[str, Any]] = None,
    validate_startup_config: bool = True,
    constructor_path: Optional[str] = None,
    default_path: Optional[str] = None,
):
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
                "Startup validation failed, continuing with default configuration: %s",
                e,
                exc_info=True,
            )
            logger.debug("Validation errors: %s", e.errors if hasattr(e, "errors") else "unknown")
    if config is None:
        container = ApplicationContainer.create_for_environment("development")
    else:
        container = ApplicationContainer(config)
    fire_event(DIContainerInitializationEvent())
    try:
        yield container
    finally:
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
    with application_container_context(
        config,
        validate_startup_config=True,
        constructor_path=constructor_path,
        default_path=default_path,
    ) as container:
        return container.get_agent_runner(use_tools)

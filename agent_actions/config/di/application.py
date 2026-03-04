"""
Application Container for managing all DI configuration and bootstrapping.

This module provides the main application container that sets up all dependencies
and provides factory methods for creating key application components.
"""

import logging
from typing import Dict, Any, Optional, TYPE_CHECKING

from agent_actions.config.di.configurator import DIConfigurator, ConfigurationProfile
from agent_actions.errors import ConfigValidationError
from agent_actions.config.di.container import (
    DependencyContainer,
    ProcessorFactory,
)

from agent_actions.workflow.runner import AgentRunner

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class ApplicationContainer:
    """Main application container that manages all dependencies."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        container: Optional[DependencyContainer] = None,
    ):
        """
        Initialize the application container.

        Args:
            config: Optional configuration dictionary.
                Uses development profile if not provided.
            container: Optional pre-configured DependencyContainer.
                When provided, skips DIConfigurator.configure_container().
        """
        if config is None:
            config = ConfigurationProfile.development()
        self.config = config
        self.container = container or DIConfigurator.configure_container(config)
        self.processor_factory = DIConfigurator.create_processor_factory(self.container)

    def get_agent_runner(
        self,
        use_tools: bool = True,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> AgentRunner:
        """
        Create an AgentRunner with all dependencies injected.

        Args:
            use_tools: Whether the agent runner should use tools.
            storage_backend: Optional storage backend for data persistence.

        Returns:
            Configured AgentRunner instance.
        """
        return AgentRunner(
            use_tools=use_tools,
            processor_factory=self.processor_factory,
            storage_backend=storage_backend,
        )

    def get_processor_factory(self) -> ProcessorFactory:
        """
        Get the processor factory for creating processors.

        Returns:
            ProcessorFactory instance.
        """
        return self.processor_factory

    def get_dependency_container(self) -> DependencyContainer:
        """
        Get the underlying dependency container.

        Returns:
            DependencyContainer instance.
        """
        return self.container

    @classmethod
    def create_for_environment(cls, environment: str) -> "ApplicationContainer":
        """
        Create application container for specific environment.

        Args:
            environment: Environment name

        Returns:
            ApplicationContainer configured for the environment.
        """
        profiles = {
            "development": ConfigurationProfile.development,
            "production": ConfigurationProfile.production,
            "testing": ConfigurationProfile.testing,
        }
        profile_fn = profiles.get(environment)
        if profile_fn is None:
            raise ConfigValidationError(
                "environment",
                f"Unknown environment: {environment}",
                context={
                    "environment": environment,
                    "valid_environments": list(profiles),
                    "operation": "create_for_environment",
                },
            )
        return cls(profile_fn())

    @classmethod
    def create_for_testing(cls) -> "ApplicationContainer":
        """
        Create application container configured for testing.

        Returns:
            ApplicationContainer with test dependencies.
        """
        return cls(
            config=ConfigurationProfile.testing(),
            container=DIConfigurator.configure_for_testing(),
        )

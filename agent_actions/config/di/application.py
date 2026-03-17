"""Application container for managing DI configuration and bootstrapping."""

import logging
from typing import TYPE_CHECKING, Optional

from agent_actions.config.di.configurator import ConfigurationProfile, DIConfigurator
from agent_actions.config.di.container import (
    DependencyContainer,
    ProcessorFactory,
)
from agent_actions.config.di.types import DIConfig
from agent_actions.errors import ConfigValidationError
from agent_actions.workflow.runner import ActionRunner

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class ApplicationContainer:
    """Main application container that manages all dependencies."""

    def __init__(
        self,
        config: DIConfig | None = None,
        *,
        container: DependencyContainer | None = None,
    ):
        """Initialize the application container.

        Args:
            config: Optional configuration dictionary.
                Uses development profile if not provided.
            container: Optional pre-configured DependencyContainer.
                When provided, skips DIConfigurator.configure_container().
        """
        if config is None:
            config = ConfigurationProfile.development()
        self.config: DIConfig = config
        self.container = container or DIConfigurator.configure_container(config)
        self.processor_factory = DIConfigurator.create_processor_factory(self.container)

    def get_action_runner(
        self,
        use_tools: bool = True,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> ActionRunner:
        """Create an ActionRunner with all dependencies injected."""
        return ActionRunner(
            use_tools=use_tools,
            processor_factory=self.processor_factory,
            storage_backend=storage_backend,
        )

    def get_processor_factory(self) -> ProcessorFactory:
        """Get the processor factory for creating processors."""
        return self.processor_factory

    def get_dependency_container(self) -> DependencyContainer:
        """Get the underlying dependency container."""
        return self.container

    @classmethod
    def create_for_environment(cls, environment: str) -> "ApplicationContainer":
        """Create application container for a specific environment.

        Raises:
            ConfigValidationError: If the environment name is not recognized.
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
        """Create application container configured for testing."""
        return cls(
            config=ConfigurationProfile.testing(),
            container=DIConfigurator.configure_for_testing(),
        )

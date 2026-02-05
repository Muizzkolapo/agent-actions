"""
Application Container for managing all DI configuration and bootstrapping.

This module provides the main application container that sets up all dependencies
and provides factory methods for creating key application components.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, Any, Optional, TYPE_CHECKING

from agent_actions.config.di.configurator import DIConfigurator, ConfigurationProfile
from agent_actions.config.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    ISourceDataLoader,
)
from agent_actions.errors import ConfigValidationError, DependencyError
from agent_actions.input.loaders.source_data import SourceDataLoader
from agent_actions.config.di.container import (
    DependencyContainer,
    ProcessorFactory,
    registry,
)
from agent_actions.input.preprocessing.processing.data_processor import DataProcessor
from agent_actions.prompt.data_generator import DataGenerator

from agent_actions.workflow.runner import AgentRunner

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class ApplicationContainer:
    """Main application container that manages all dependencies."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the application container.

        Args:
            config: Optional configuration dictionary.
                Uses development profile if not provided.
        """
        if config is None:
            config = ConfigurationProfile.development()
        self.config = config
        self.container = DIConfigurator.configure_container(config)
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

    def _get_dependency_configs_for_agent(
        self, agent_config: Dict, agent_configs: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, Dict]:
        """
        Extract configs for all dependencies of an agent.

        Args:
            agent_config: Configuration for the agent
            agent_configs: Full dict mapping agent names to their configs

        Returns:
            Dict mapping dependency names to their configs
        """
        if not agent_configs:
            return {}
        dependency_names = agent_config.get("dependencies", [])
        dependency_configs = {}
        for dep_name in dependency_names:
            if dep_name in agent_configs:
                dependency_configs[dep_name] = agent_configs[dep_name]
        return dependency_configs

    def _get_source_loader(self, agent_name: str, storage_backend: "StorageBackend"):
        """Get source loader from container or create with storage backend."""
        try:
            source_loader = self.container.get(ISourceDataLoader)
            logger.debug(
                "Retrieved ISourceDataLoader from DI container",
                extra={"agent_name": agent_name},
            )
            return source_loader
        except (KeyError, ValueError, AttributeError, TypeError, DependencyError):
            logger.debug(
                "Creating SourceDataLoader with storage backend",
                extra={"agent_name": agent_name},
            )
            return SourceDataLoader(agent_name=agent_name, storage_backend=storage_backend)

    def _get_data_generator(
        self,
        agent_config: Dict,
        agent_name: str,
        _idx: int,
        agent_configs: Optional[Dict[str, Dict]],
        agent_indices: Dict,
    ):
        """Get data generator from container or create manually."""
        try:
            return self.container.get(IGenerator)
        except (KeyError, ValueError, AttributeError, TypeError, DependencyError):
            dependency_configs = self._get_dependency_configs_for_agent(agent_config, agent_configs)
            return DataGenerator(agent_config, agent_name, dependency_configs, agent_indices)

    def _get_data_processor(self, agent_config: Dict):
        """Get data processor from container or create manually."""
        try:
            return self.container.get(IDataProcessor)
        except (KeyError, ValueError, AttributeError, TypeError, DependencyError):
            return DataProcessor(agent_config)

    @classmethod
    def create_for_environment(cls, environment: str) -> "ApplicationContainer":
        """
        Create application container for specific environment.

        Args:
            environment: Environment name

        Returns:
            ApplicationContainer configured for the environment.
        """
        if environment == "development":
            config = ConfigurationProfile.development()
        elif environment == "production":
            config = ConfigurationProfile.production()
        elif environment == "testing":
            config = ConfigurationProfile.testing()
        else:
            raise ConfigValidationError(
                "environment",
                f"Unknown environment: {environment}",
                context={
                    "environment": environment,
                    "valid_environments": ["development", "production", "testing"],
                    "operation": "create_for_environment",
                },
            )
        return cls(config)

    @classmethod
    def create_for_testing(cls) -> "ApplicationContainer":
        """
        Create application container configured for testing.

        Returns:
            ApplicationContainer with test dependencies.
        """
        container = DIConfigurator.configure_for_testing()
        app_container = cls.__new__(cls)
        app_container.config = ConfigurationProfile.testing()
        app_container.container = container
        app_container.processor_factory = ProcessorFactory(container, registry)
        return app_container

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on all registered services.

        Returns:
            Health check results.
        """
        results = {"status": "healthy", "services": {}, "timestamp": None}
        try:
            self.container.get(IDataLoader)
            results["services"]["data_loader"] = "healthy"
            self.container.get(IDataProcessor)
            results["services"]["data_processor"] = "healthy"
            self.container.get(IGenerator)
            results["services"]["generator"] = "healthy"
            # BatchService not registered, create instance for health check
            # Import here to avoid circular dependency
            from agent_actions.llm.batch.service import BatchService

            BatchService()
            results["services"]["batch_service"] = "healthy"
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, ImportError) as e:
            results["status"] = "unhealthy"
            results["error"] = str(e)
        results["timestamp"] = datetime.now(timezone.utc).isoformat()
        return results

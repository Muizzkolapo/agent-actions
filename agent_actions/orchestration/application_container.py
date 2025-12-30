"""
Application Container for managing all DI configuration and bootstrapping.

This module provides the main application container that sets up all dependencies
and provides factory methods for creating key application components.
"""

import datetime
import logging
from typing import Dict, Any, Optional

from agent_actions.configuration.di_configurator import DIConfigurator, ConfigurationProfile
from agent_actions.configuration.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    ISourceDataLoader,
)
from agent_actions.errors import ConfigValidationError, DependencyError
from agent_actions.input_loading.extractors_source_data_loader import SourceDataLoader
from agent_actions.state_management.path_manager import PathManager
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.orchestration.dependency_injection import (
    DependencyContainer,
    ProcessorFactory,
    registry,
)
from agent_actions.orchestration.node_mapper import NodeMappingService
from agent_actions.preprocessing.processing.data_processor import DataProcessor
from agent_actions.prompt_generation.data_generator import DataGenerator

from .agent_runner import AgentRunner

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

    def get_agent_runner(self, use_tools: bool = True) -> AgentRunner:
        """
        Create an AgentRunner with all dependencies injected.

        Args:
            use_tools: Whether the agent runner should use tools.

        Returns:
            Configured AgentRunner instance.
        """
        return AgentRunner(use_tools=use_tools, processor_factory=self.processor_factory)

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

    def _get_source_loader(self, agent_name: str, idx: int):
        """Get source loader from container with fallbacks."""
        try:
            source_loader = self.container.get(ISourceDataLoader)
            logger.debug(
                "Retrieved ISourceDataLoader from DI container",
                extra={"agent_name": agent_name, "idx": idx},
            )
            return source_loader
        except (KeyError, ValueError, AttributeError, TypeError, DependencyError):
            pass

        try:
            source_loader = self.container.get(IDataLoader)
            logger.info(
                "Using IDataLoader as fallback for ISourceDataLoader",
                extra={"agent_name": agent_name, "idx": idx},
            )
            return source_loader
        except (KeyError, ValueError, AttributeError, TypeError, DependencyError):
            logger.debug(
                "Creating source_loader via processor_factory",
                extra={"agent_name": agent_name, "idx": idx},
            )
            path_manager = self.container.get(PathManager)
            return SourceDataLoader(agent_name=agent_name, path_manager=path_manager)

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

    def create_target_content_processor(
        self,
        agent_config: Dict,
        agent_name: str,
        idx: int,
        agent_configs: Optional[Dict[str, Dict]] = None,
    ):
        """
        Create a TargetContentProcessor with all dependencies injected.

        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            idx: Index of the config being processed
            agent_configs: Optional dict mapping agent names to their configs

        Returns:
            TargetContentProcessor instance with injected dependencies.
        """
        source_loader = self._get_source_loader(agent_name, idx)

        agent_indices = (
            NodeMappingService.build_agent_index_map(agent_configs) if agent_configs else {}
        )

        data_generator = self._get_data_generator(
            agent_config, agent_name, idx, agent_configs, agent_indices
        )
        data_processor = self._get_data_processor(agent_config)

        dependency_configs = self._get_dependency_configs_for_agent(agent_config, agent_configs)
        batch_service = BatchService(
            agent_indices=agent_indices, dependency_configs=dependency_configs or agent_configs
        )

        return self.processor_factory.create_processor(
            "target_content",
            agent_config=agent_config,
            agent_name=agent_name,
            idx=idx,
            source_loader=source_loader,
            data_generator=data_generator,
            data_processor=data_processor,
            batch_service=batch_service,
        )

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

    def configure_logging(self):
        """Configure application logging based on container settings."""
        return None

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
            BatchService()
            results["services"]["batch_service"] = "healthy"
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, ImportError) as e:
            results["status"] = "unhealthy"
            results["error"] = str(e)
        results["timestamp"] = datetime.datetime.utcnow().isoformat()
        return results

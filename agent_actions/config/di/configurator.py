"""Dependency injection configuration for agent-actions."""

from agent_actions.config.di.container import (
    DependencyContainer,
    ProcessorFactory,
    registry,
)
from agent_actions.config.di.types import DIConfig
from agent_actions.config.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    ISourceDataLoader,
)


class DIConfigurator:
    """Configures the dependency container with application services."""

    @staticmethod
    def configure_container(config: DIConfig) -> DependencyContainer:
        """Configure the container with all dependencies."""
        container = DependencyContainer()
        DIConfigurator._register_core_services(container)
        DIConfigurator._register_processors(container)
        DIConfigurator._register_utilities(container)
        return container

    @staticmethod
    def _register_core_services(container: DependencyContainer):
        """Register core application services."""
        from agent_actions.config.paths import PathManager

        container.register_singleton(PathManager, PathManager)

    @staticmethod
    def _register_processors(container: DependencyContainer):
        """Register processor implementations."""
        from agent_actions.input.loaders.json import JsonLoader
        from agent_actions.input.loaders.source_data import SourceDataLoader
        from agent_actions.input.preprocessing.processing.data_processor import DataProcessor
        from agent_actions.prompt.data_generator import DataGenerator

        container.register_transient(IDataProcessor, DataProcessor)  # type: ignore[type-abstract]  # intentional DI: concrete impl satisfies abstract interface
        container.register_transient(IGenerator, DataGenerator)  # type: ignore[type-abstract]  # intentional DI: concrete impl satisfies abstract interface
        container.register_transient(ISourceDataLoader, SourceDataLoader)  # type: ignore[type-abstract]  # intentional DI: concrete impl satisfies abstract interface
        container.register_transient(IDataLoader, JsonLoader)  # type: ignore[type-abstract]  # intentional DI: concrete impl satisfies abstract interface

    @staticmethod
    def _register_utilities(container: DependencyContainer):
        """Register utility services."""
        from agent_actions.logging.factory import LoggerFactory
        from agent_actions.prompt.handler import PromptLoader

        container.register_singleton(PromptLoader, PromptLoader)
        container.register_singleton(LoggerFactory, LoggerFactory)

    @staticmethod
    def create_processor_factory(container: DependencyContainer) -> ProcessorFactory:
        """Create a processor factory with the configured container."""
        return ProcessorFactory(container, registry)

    @staticmethod
    def configure_for_testing() -> DependencyContainer:
        """Configure container for testing with mocks."""
        from unittest.mock import Mock

        container = DependencyContainer()
        mock_loader = Mock()
        mock_loader.load_source_data.return_value = [
            {"source_guid": "test-guid-1", "content": "test content 1"},
            {"source_guid": "test-guid-2", "content": "test content 2"},
        ]
        container.register_instance(ISourceDataLoader, mock_loader)
        container.register_instance(IDataLoader, mock_loader)

        def processor_factory():
            m = Mock()
            m.process_item.return_value = []
            return m

        def generator_factory():
            m = Mock()
            m.create_agent_with_data.return_value = ([], True)
            return m

        container.register_factory(IDataProcessor, processor_factory)  # type: ignore[type-abstract]  # intentional DI: factory returns mock satisfying abstract interface
        container.register_factory(IGenerator, generator_factory)  # type: ignore[type-abstract]  # intentional DI: factory returns mock satisfying abstract interface
        from agent_actions.config.paths import PathManager

        container.register_instance(PathManager, Mock(spec=PathManager))
        return container


class ConfigurationProfile:
    """Predefined configuration profiles for different environments."""

    @staticmethod
    def development() -> DIConfig:
        """Development configuration profile."""
        return {
            "environment": "development",
            "logging": {"level": "DEBUG", "enable_console": True},
            "processors": {"cache_enabled": False, "parallel_processing": False},
            "services": {"batch_size": 10, "timeout": 30},
        }

    @staticmethod
    def production() -> DIConfig:
        """Production configuration profile."""
        return {
            "environment": "production",
            "logging": {"level": "INFO", "enable_console": False},
            "processors": {"cache_enabled": True, "parallel_processing": True},
            "services": {"batch_size": 100, "timeout": 120},
        }

    @staticmethod
    def testing() -> DIConfig:
        """Testing configuration profile."""
        return {
            "environment": "testing",
            "logging": {"level": "ERROR", "enable_console": False},
            "processors": {"cache_enabled": False, "parallel_processing": False},
            "services": {"batch_size": 5, "timeout": 10},
        }

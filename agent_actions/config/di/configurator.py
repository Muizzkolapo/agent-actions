"""
Dependency Injection Configuration for Agent Actions.

This module configures the DI container with all application dependencies
based on configuration settings.
"""

from typing import Any, Dict

from agent_actions.config.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    ISourceDataLoader,
)
from agent_actions.config.di.container import (
    DependencyContainer,
    ProcessorFactory,
    registry,
)


class DIConfigurator:
    """Configures the dependency container with application services."""

    @staticmethod
    def configure_container(config: Dict[str, Any]) -> DependencyContainer:
        """Configure the container with all dependencies."""
        container = DependencyContainer()
        DIConfigurator._register_core_services(container, config)
        DIConfigurator._register_processors(container, config)
        DIConfigurator._register_utilities(container, config)
        return container

    @staticmethod
    def _register_core_services(
        container: DependencyContainer,
        config: Dict[str, Any],
    ):
        """Register core application services."""
        from agent_actions.llm.batch.batch_service import BatchService
        from agent_actions.llm.realtime.output_handler import OutputHandler
        from agent_actions.config.paths import PathManager

        container.register_singleton(PathManager, PathManager)
        container.register_singleton(BatchService, BatchService)
        container.register_transient(OutputHandler, OutputHandler)

    @staticmethod
    def _register_processors(
        container: DependencyContainer,
        config: Dict[str, Any],
    ):
        """Register processor implementations."""
        from agent_actions.input.preprocessing.processing.data_processor import DataProcessor
        from agent_actions.prompt.data_generator import DataGenerator

        container.register_transient(IDataProcessor, DataProcessor)
        container.register_transient(IGenerator, DataGenerator)
        # Note: ISourceDataLoader is NOT registered here because SourceDataLoader
        # requires runtime parameters (agent_name) that can't be auto-injected.
        # Use ApplicationContainer._get_source_loader() factory method instead.

    @staticmethod
    def _register_utilities(
        container: DependencyContainer,
        config: Dict[str, Any],
    ):
        """Register utility services."""
        from agent_actions.logging.factory import LoggerFactory
        from agent_actions.input.preprocessing.transformation.data_transformer import (
            DataTransformer,
        )
        from agent_actions.prompt.handler import PromptLoader
        from agent_actions.prompt.enricher import SampleEnricher

        container.register_singleton(DataTransformer, DataTransformer)
        container.register_singleton(PromptLoader, PromptLoader)
        container.register_singleton(SampleEnricher, SampleEnricher)
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
            m.separate_side_output.return_value = ([], [])
            return m

        def generator_factory():
            m = Mock()
            m.create_agent_with_data.return_value = ([], True)
            return m

        container.register_factory(IDataProcessor, processor_factory)
        container.register_factory(IGenerator, generator_factory)
        from agent_actions.llm.batch.batch_service import BatchService
        from agent_actions.config.paths import PathManager

        container.register_instance(PathManager, Mock(spec=PathManager))
        container.register_instance(BatchService, Mock(spec=BatchService))
        return container


class ConfigurationProfile:
    """Predefined configuration profiles for different environments."""

    @staticmethod
    def development() -> Dict[str, Any]:
        """Development configuration profile."""
        return {
            "environment": "development",
            "logging": {"level": "DEBUG", "enable_console": True},
            "processors": {"cache_enabled": False, "parallel_processing": False},
            "services": {"batch_size": 10, "timeout": 30},
        }

    @staticmethod
    def production() -> Dict[str, Any]:
        """Production configuration profile."""
        return {
            "environment": "production",
            "logging": {"level": "INFO", "enable_console": False},
            "processors": {"cache_enabled": True, "parallel_processing": True},
            "services": {"batch_size": 100, "timeout": 120},
        }

    @staticmethod
    def testing() -> Dict[str, Any]:
        """Testing configuration profile."""
        return {
            "environment": "testing",
            "logging": {"level": "ERROR", "enable_console": False},
            "processors": {"cache_enabled": False, "parallel_processing": False},
            "services": {"batch_size": 5, "timeout": 10},
        }

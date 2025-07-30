"""
Dependency Injection Configuration for Agent Actions.

This module configures the DI container with all application dependencies
based on configuration settings.
"""

from typing import Dict, Any
from .dependency_injection import DependencyContainer, ProcessorFactory, registry
from ..common.interfaces.interfaces import (
    IDataLoader, IDataProcessor, IGenerator, IContentProcessor
)


class DIConfigurator:
    """Configures the dependency container with application services."""
    
    @staticmethod
    def configure_container(config: Dict[str, Any]) -> DependencyContainer:
        """Configure the container with all dependencies."""
        container = DependencyContainer()
        
        # Register core services
        DIConfigurator._register_core_services(container, config)
        
        # Register processors
        DIConfigurator._register_processors(container, config)
        
        # Register utilities
        DIConfigurator._register_utilities(container, config)
        
        return container
    
    @staticmethod
    def _register_core_services(container: DependencyContainer, config: Dict[str, Any]):
        """Register core application services."""
        from ..services.batch_service import BatchService
        from .path_manager import PathManager
        
        # Core services as singletons
        container.register_singleton(PathManager, PathManager)
        container.register_singleton(BatchService, BatchService)
        
        # Output handler as transient (may need different configurations)
        from ..processors.target_processor.output_handler import OutputHandler
        container.register_transient(OutputHandler, OutputHandler)
    
    @staticmethod
    def _register_processors(container: DependencyContainer, config: Dict[str, Any]):
        """Register processor implementations."""
        from ..processors.source_processor.source_data_loader import SourceDataLoader
        from ..processors.target_processor.data_processor import DataProcessor
        from ..processors.target_processor.data_generator import DataGenerator
        
        # Data loaders - note: SourceDataLoader requires runtime parameters
        # It will be created by the factory with specific agent_name
        
        # Data processors
        container.register_transient(IDataProcessor, DataProcessor)
        
        # Data generators
        container.register_transient(IGenerator, DataGenerator)
    
    @staticmethod
    def _register_utilities(container: DependencyContainer, config: Dict[str, Any]):
        """Register utility services."""
        from ..transformers.data_transformer import DataTransformer
        from ..handlers.prompt_handler import PromptLoader
        from ..processors.prompt_processor.sample_enricher import SampleEnricher
        
        # Register utilities as singletons (stateless services)
        container.register_singleton(DataTransformer, DataTransformer)
        container.register_singleton(PromptLoader, PromptLoader)
        container.register_singleton(SampleEnricher, SampleEnricher)
    
    @staticmethod
    def create_processor_factory(container: DependencyContainer) -> ProcessorFactory:
        """Create a processor factory with the configured container."""
        return ProcessorFactory(container, registry)
    
    @staticmethod
    def configure_for_testing() -> DependencyContainer:
        """Configure container for testing with mocks."""
        from unittest.mock import Mock
        
        container = DependencyContainer()
        
        # Register mocks for testing
        container.register_instance(IDataLoader, Mock(spec=IDataLoader))
        container.register_instance(IDataProcessor, Mock(spec=IDataProcessor))
        container.register_instance(IGenerator, Mock(spec=IGenerator))
        
        # Mock core services
        from .path_manager import PathManager
        from ..services.batch_service import BatchService
        
        container.register_instance(PathManager, Mock(spec=PathManager))
        container.register_instance(BatchService, Mock(spec=BatchService))
        
        return container


class ConfigurationProfile:
    """Predefined configuration profiles for different environments."""
    
    @staticmethod
    def development() -> Dict[str, Any]:
        """Development configuration profile."""
        return {
            'environment': 'development',
            'logging': {
                'level': 'DEBUG',
                'enable_console': True
            },
            'processors': {
                'cache_enabled': False,
                'parallel_processing': False
            },
            'services': {
                'batch_size': 10,
                'timeout': 30
            }
        }
    
    @staticmethod
    def production() -> Dict[str, Any]:
        """Production configuration profile."""
        return {
            'environment': 'production',
            'logging': {
                'level': 'INFO',
                'enable_console': False
            },
            'processors': {
                'cache_enabled': True,
                'parallel_processing': True
            },
            'services': {
                'batch_size': 100,
                'timeout': 120
            }
        }
    
    @staticmethod
    def testing() -> Dict[str, Any]:
        """Testing configuration profile."""
        return {
            'environment': 'testing',
            'logging': {
                'level': 'ERROR',
                'enable_console': False
            },
            'processors': {
                'cache_enabled': False,
                'parallel_processing': False
            },
            'services': {
                'batch_size': 5,
                'timeout': 10
            }
        }
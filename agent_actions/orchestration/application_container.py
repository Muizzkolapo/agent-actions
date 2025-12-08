"""
Application Container for managing all DI configuration and bootstrapping.

This module provides the main application container that sets up all dependencies
and provides factory methods for creating key application components.
"""
import logging
from typing import Dict, Any, Optional
from agent_actions.orchestration.dependency_injection import DependencyContainer, ProcessorFactory, registry
from agent_actions.configuration.di_configurator import DIConfigurator, ConfigurationProfile
from .agent_runner import AgentRunner
from agent_actions.configuration.interfaces import IDataLoader, IDataProcessor, IGenerator, ISourceDataLoader

logger = logging.getLogger(__name__)

class ApplicationContainer:
    """Main application container that manages all dependencies."""

    def __init__(self, config: Optional[Dict[str, Any]]=None):
        """
        Initialize the application container.
        
        Args:
            config: Optional configuration dictionary. Uses development profile if not provided.
        """
        if config is None:
            config = ConfigurationProfile.development()
        self.config = config
        self.container = DIConfigurator.configure_container(config)
        self.processor_factory = DIConfigurator.create_processor_factory(self.container)

    def get_agent_runner(self, use_tools: bool=True) -> AgentRunner:
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

    def _get_dependency_configs_for_agent(self, agent_config: Dict, agent_configs: Optional[Dict[str, Dict]]=None) -> Dict[str, Dict]:
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
        dependency_names = agent_config.get('dependencies', [])
        dependency_configs = {}
        for dep_name in dependency_names:
            if dep_name in agent_configs:
                dependency_configs[dep_name] = agent_configs[dep_name]
        return dependency_configs

    def create_target_content_processor(self, agent_config: Dict, agent_name: str, idx: int, agent_configs: Optional[Dict[str, Dict]]=None):
        """
        Create a TargetContentProcessor with all dependencies injected.

        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            idx: Index of the config being processed
            agent_configs: Optional dict mapping agent names to their configs (for dependency resolution)

        Returns:
            TargetContentProcessor instance with injected dependencies.
        """
        from agent_actions.prompt_generation.data_generator import DataGenerator
        from agent_actions.preprocessing.processing.data_processor import DataProcessor
        from agent_actions.llm_invocation.batch.batch_service import BatchService
        from agent_actions.orchestration.node_mapper import NodeMappingService

        try:
            source_loader = self.container.get(ISourceDataLoader)
            logger.debug(
                "Retrieved ISourceDataLoader from DI container",
                extra={'agent_name': agent_name, 'idx': idx}
            )
        except Exception as e:
            logger.debug(
                "ISourceDataLoader not in container, trying IDataLoader fallback",
                extra={
                    'agent_name': agent_name,
                    'idx': idx,
                    'error': str(e),
                    'fallback_attempt': 'IDataLoader'
                }
            )
            try:
                source_loader = self.container.get(IDataLoader)
                logger.info(
                    "Using IDataLoader as fallback for ISourceDataLoader",
                    extra={'agent_name': agent_name, 'idx': idx}
                )
            except Exception as e2:
                logger.debug(
                    "Creating source_loader via processor_factory (final fallback)",
                    extra={
                        'agent_name': agent_name,
                        'idx': idx,
                        'first_error': str(e),
                        'second_error': str(e2),
                        'fallback': 'processor_factory'
                    }
                )
                source_loader = self.processor_factory.create_source_data_loader(agent_name)

        # Build agent indices mapping for historical node data loading
        agent_indices = NodeMappingService.build_agent_index_map(agent_configs) if agent_configs else {}

        try:
            data_generator = self.container.get(IGenerator)
            logger.debug(
                "Retrieved IGenerator from DI container",
                extra={'agent_name': agent_name, 'idx': idx}
            )
        except Exception as e:
            logger.debug(
                "IGenerator not in container, creating DataGenerator manually",
                extra={
                    'agent_name': agent_name,
                    'idx': idx,
                    'error': str(e),
                    'fallback': 'DataGenerator'
                }
            )
            dependency_configs = self._get_dependency_configs_for_agent(agent_config, agent_configs)
            data_generator = DataGenerator(agent_config, agent_name, dependency_configs, agent_indices)

        try:
            data_processor = self.container.get(IDataProcessor)
            logger.debug(
                "Retrieved IDataProcessor from DI container",
                extra={'agent_name': agent_name, 'idx': idx}
            )
        except Exception as e:
            logger.debug(
                "IDataProcessor not in container, creating DataProcessor manually",
                extra={
                    'agent_name': agent_name,
                    'idx': idx,
                    'error': str(e),
                    'fallback': 'DataProcessor'
                }
            )
            data_processor = DataProcessor(agent_config)

        # Create BatchService with agent_indices and dependency_configs for historical node loading
        dependency_configs = self._get_dependency_configs_for_agent(agent_config, agent_configs)
        batch_service = BatchService(
            agent_indices=agent_indices,
            dependency_configs=dependency_configs or agent_configs
        )
        return self.processor_factory.create_processor('target_content', agent_config=agent_config, agent_name=agent_name, idx=idx, source_loader=source_loader, data_generator=data_generator, data_processor=data_processor, batch_service=batch_service)

    @classmethod
    def create_for_environment(cls, environment: str) -> 'ApplicationContainer':
        """
        Create application container for specific environment.
        
        Args:
            environment: Environment name ('development', 'production', 'testing')
            
        Returns:
            ApplicationContainer configured for the environment.
        """
        from agent_actions.errors import ConfigValidationError  # New modular pattern!
        if environment == 'development':
            config = ConfigurationProfile.development()
        elif environment == 'production':
            config = ConfigurationProfile.production()
        elif environment == 'testing':
            config = ConfigurationProfile.testing()
        else:
            raise ConfigValidationError('environment', f'Unknown environment: {environment}', context={'environment': environment, 'valid_environments': ['development', 'production', 'testing'], 'operation': 'create_for_environment'})
        return cls(config)

    @classmethod
    def create_for_testing(cls) -> 'ApplicationContainer':
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
        pass

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on all registered services.
        
        Returns:
            Health check results.
        """
        results = {'status': 'healthy', 'services': {}, 'timestamp': None}
        try:
            from agent_actions.configuration.interfaces import IDataLoader, IDataProcessor, IGenerator
            from agent_actions.llm_invocation.batch.batch_service import BatchService
            self.container.get(IDataLoader)
            results['services']['data_loader'] = 'healthy'
            self.container.get(IDataProcessor)
            results['services']['data_processor'] = 'healthy'
            self.container.get(IGenerator)
            results['services']['generator'] = 'healthy'
            # BatchService is no longer registered in container, create instance for health check
            BatchService()
            results['services']['batch_service'] = 'healthy'
        except Exception as e:
            results['status'] = 'unhealthy'
            results['error'] = str(e)
        import datetime
        results['timestamp'] = datetime.datetime.utcnow().isoformat()
        return results
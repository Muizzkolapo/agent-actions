"""
Application Container for managing all DI configuration and bootstrapping.

This module provides the main application container that sets up all dependencies
and provides factory methods for creating key application components.
"""

from typing import Dict, Any, Optional
from ..graph.dependency_injection import DependencyContainer, ProcessorFactory, registry
from ..bootstrap import DIConfigurator, ConfigurationProfile
from .agent_runner import AgentRunner
from ..contracts.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    ISourceDataLoader,
)


class ApplicationContainer:
    """Main application container that manages all dependencies."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
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
    
    def create_target_content_processor(self, agent_config: Dict, agent_name: str, idx: int):
        """
        Create a TargetContentProcessor with all dependencies injected.
        
        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            idx: Index of the config being processed
            
        Returns:
            TargetContentProcessor instance with injected dependencies.
        """
        from agent_actions.agents.generators.data_generator import DataGenerator
        from agent_actions.agents.transformers.data_processor import DataProcessor
        from agent_actions.tasks.services.batch_service import BatchService

        # Use mocked dependencies when available
        try:
            source_loader = self.container.get(ISourceDataLoader)
        except Exception:
            try:
                source_loader = self.container.get(IDataLoader)
            except Exception:
                source_loader = self.processor_factory.create_source_data_loader(agent_name)

        try:
            data_generator = self.container.get(IGenerator)
        except Exception:
            data_generator = DataGenerator(agent_config, agent_name)

        try:
            data_processor = self.container.get(IDataProcessor)
        except Exception:
            data_processor = DataProcessor(agent_config)

        batch_service = self.container.get(BatchService)

        # Create the processor with explicit dependencies
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
    def create_for_environment(cls, environment: str) -> 'ApplicationContainer':
        """
        Create application container for specific environment.
        
        Args:
            environment: Environment name ('development', 'production', 'testing')
            
        Returns:
            ApplicationContainer configured for the environment.
        """
        from agent_actions.core.exceptions import ConfigValidationError

        if environment == 'development':
            config = ConfigurationProfile.development()
        elif environment == 'production':
            config = ConfigurationProfile.production()
        elif environment == 'testing':
            config = ConfigurationProfile.testing()
        else:
            raise ConfigValidationError(
                "environment",
                f"Unknown environment: {environment}",
                context={'environment': environment, 'valid_environments': ['development', 'production', 'testing'], 'operation': 'create_for_environment'}
            )

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
        # This would integrate with your existing logging setup
        pass
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on all registered services.
        
        Returns:
            Health check results.
        """
        results = {
            'status': 'healthy',
            'services': {},
            'timestamp': None
        }
        
        # Check if key services can be resolved
        try:
            from ..contracts.interfaces import (
                IDataLoader,
                IDataProcessor,
                IGenerator,
            )
            from agent_actions.tasks.services.batch_service import BatchService
            
            # Try to resolve key services
            self.container.get(IDataLoader)
            results['services']['data_loader'] = 'healthy'
            
            self.container.get(IDataProcessor)
            results['services']['data_processor'] = 'healthy'
            
            self.container.get(IGenerator)
            results['services']['generator'] = 'healthy'
            
            self.container.get(BatchService)
            results['services']['batch_service'] = 'healthy'
            
        except Exception as e:
            results['status'] = 'unhealthy'
            results['error'] = str(e)
        
        import datetime
        results['timestamp'] = datetime.datetime.utcnow().isoformat()
        
        return results
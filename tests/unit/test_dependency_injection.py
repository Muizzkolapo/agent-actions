"""
Unit tests for the dependency injection framework.

Tests the core DI container, registry, and factory functionality.
"""

import pytest
from unittest.mock import Mock
from typing import Protocol

from agent_actions.core.graph.dependency_injection import (
    DependencyContainer, ProcessorRegistry, ProcessorFactory, ServiceLifetime
)


# Test interfaces and implementations
class ITestService(Protocol):
    def do_something(self) -> str:
        ...


class TestServiceImpl:
    def __init__(self, dependency: str = "default"):
        self.dependency = dependency
    
    def do_something(self) -> str:
        return f"Service with {self.dependency}"


class ITestDependency(Protocol):
    def get_value(self) -> str:
        ...


class TestDependencyImpl:
    def get_value(self) -> str:
        return "dependency value"


class TestServiceWithDependency:
    def __init__(self, dep: ITestDependency):
        self.dep = dep
    
    def do_something(self) -> str:
        return f"Service with {self.dep.get_value()}"


class TestDependencyContainer:
    """Test the dependency injection container."""
    
    def test_register_and_resolve_transient(self):
        """Test registering and resolving transient services."""
        # Arrange
        container = DependencyContainer()
        container.register_transient(ITestService, TestServiceImpl)
        
        # Act
        service1 = container.get(ITestService)
        service2 = container.get(ITestService)
        
        # Assert
        assert isinstance(service1, TestServiceImpl)
        assert isinstance(service2, TestServiceImpl)
        assert service1 is not service2  # Different instances for transient
    
    def test_register_and_resolve_singleton(self):
        """Test registering and resolving singleton services."""
        # Arrange
        container = DependencyContainer()
        container.register_singleton(ITestService, TestServiceImpl)
        
        # Act
        service1 = container.get(ITestService)
        service2 = container.get(ITestService)
        
        # Assert
        assert isinstance(service1, TestServiceImpl)
        assert isinstance(service2, TestServiceImpl)
        assert service1 is service2  # Same instance for singleton
    
    def test_register_instance(self):
        """Test registering a specific instance."""
        # Arrange
        container = DependencyContainer()
        instance = TestServiceImpl("custom")
        container.register_instance(ITestService, instance)
        
        # Act
        retrieved = container.get(ITestService)
        
        # Assert
        assert retrieved is instance
        assert retrieved.dependency == "custom"
    
    def test_register_factory(self):
        """Test registering a factory function."""
        # Arrange
        container = DependencyContainer()
        factory_called = False
        
        def test_factory():
            nonlocal factory_called
            factory_called = True
            return TestServiceImpl("from_factory")
        
        container.register_factory(ITestService, test_factory)
        
        # Act
        service = container.get(ITestService)
        
        # Assert
        assert factory_called
        assert isinstance(service, TestServiceImpl)
        assert service.dependency == "from_factory"
    
    def test_dependency_resolution(self):
        """Test automatic dependency resolution."""
        # Arrange
        container = DependencyContainer()
        container.register_transient(ITestDependency, TestDependencyImpl)
        container.register_transient(ITestService, TestServiceWithDependency)
        
        # Act
        service = container.get(ITestService)
        
        # Assert
        assert isinstance(service, TestServiceWithDependency)
        assert isinstance(service.dep, TestDependencyImpl)
        assert service.do_something() == "Service with dependency value"
    
    def test_has_service(self):
        """Test checking if service is registered."""
        # Arrange
        container = DependencyContainer()
        container.register_transient(ITestService, TestServiceImpl)
        
        # Act & Assert
        assert container.has(ITestService) is True
        assert container.has(ITestDependency) is False
    
    def test_unregistered_service_raises_error(self):
        """Test that requesting unregistered service raises error."""
        # Arrange
        container = DependencyContainer()
        
        # Act & Assert
        with pytest.raises(ValueError, match="Service ITestService not registered"):
            container.get(ITestService)
    
    def test_circular_dependency_detection(self):
        """Test handling of circular dependencies."""
        # This is a more advanced feature that could be implemented later
        pass


class TestProcessorRegistry:
    """Test the processor registry."""
    
    def test_register_and_get_processor(self):
        """Test processor registration and retrieval."""
        # Arrange
        registry = ProcessorRegistry()
        
        @registry.register_processor("test_processor")
        class TestProcessor:
            pass
        
        # Act
        processor_cls = registry.get_processor("test_processor")
        
        # Assert
        assert processor_cls is TestProcessor
    
    def test_register_and_get_loader(self):
        """Test loader registration and retrieval."""
        # Arrange
        registry = ProcessorRegistry()
        
        @registry.register_loader("test_loader")
        class TestLoader:
            pass
        
        # Act
        loader_cls = registry.get_loader("test_loader")
        
        # Assert
        assert loader_cls is TestLoader
    
    def test_register_and_get_generator(self):
        """Test generator registration and retrieval."""
        # Arrange
        registry = ProcessorRegistry()
        
        @registry.register_generator("test_generator")
        class TestGenerator:
            pass
        
        # Act
        generator_cls = registry.get_generator("test_generator")
        
        # Assert
        assert generator_cls is TestGenerator
    
    def test_register_and_get_service(self):
        """Test service registration and retrieval."""
        # Arrange
        registry = ProcessorRegistry()
        
        @registry.register_service("test_service")
        class TestService:
            pass
        
        # Act
        service_cls = registry.get_service("test_service")
        
        # Assert
        assert service_cls is TestService
    
    def test_unregistered_component_raises_error(self):
        """Test that requesting unregistered component raises error."""
        # Arrange
        registry = ProcessorRegistry()
        
        # Act & Assert
        with pytest.raises(ValueError, match="Processor 'unknown' not registered"):
            registry.get_processor("unknown")
    
    def test_list_registered_components(self):
        """Test listing all registered components."""
        # Arrange
        registry = ProcessorRegistry()
        
        @registry.register_processor("proc1")
        class Processor1:
            pass
        
        @registry.register_processor("proc2")
        class Processor2:
            pass
        
        # Act
        processors = registry.list_processors()
        
        # Assert
        assert len(processors) == 2
        assert "proc1" in processors
        assert "proc2" in processors
        assert processors["proc1"] is Processor1
        assert processors["proc2"] is Processor2


class TestProcessorFactory:
    """Test the processor factory."""
    
    def test_create_processor_with_dependencies(self):
        """Test creating processor with dependency injection."""
        # Arrange
        container = DependencyContainer()
        registry = ProcessorRegistry()
        
        # Register dependency
        container.register_transient(ITestDependency, TestDependencyImpl)
        
        # Register processor
        @registry.register_processor("test_processor")
        class TestProcessor:
            def __init__(self, dep: ITestDependency, config: str = "default"):
                self.dep = dep
                self.config = config
        
        factory = ProcessorFactory(container, registry)
        
        # Act
        processor = factory.create_processor("test_processor", config="custom")
        
        # Assert
        assert isinstance(processor, TestProcessor)
        assert isinstance(processor.dep, TestDependencyImpl)
        assert processor.config == "custom"
    
    def test_create_loader_with_dependencies(self):
        """Test creating loader with dependency injection."""
        # Arrange
        container = DependencyContainer()
        registry = ProcessorRegistry()
        
        container.register_transient(ITestDependency, TestDependencyImpl)
        
        @registry.register_loader("test_loader")
        class TestLoader:
            def __init__(self, dep: ITestDependency):
                self.dep = dep
        
        factory = ProcessorFactory(container, registry)
        
        # Act
        loader = factory.create_loader("test_loader")
        
        # Assert
        assert isinstance(loader, TestLoader)
        assert isinstance(loader.dep, TestDependencyImpl)
    
    def test_override_dependencies(self):
        """Test overriding dependencies in factory creation."""
        # Arrange
        container = DependencyContainer()
        registry = ProcessorRegistry()
        
        container.register_transient(ITestDependency, TestDependencyImpl)
        
        @registry.register_processor("test_processor")
        class TestProcessor:
            def __init__(self, dep: ITestDependency, name: str):
                self.dep = dep
                self.name = name
        
        factory = ProcessorFactory(container, registry)
        override_dep = Mock(spec=ITestDependency)
        
        # Act
        processor = factory.create_processor("test_processor", 
                                           dep=override_dep, 
                                           name="test")
        
        # Assert
        assert isinstance(processor, TestProcessor)
        assert processor.dep is override_dep
        assert processor.name == "test"
    
    def test_unresolvable_dependency_raises_error(self):
        """Test that unresolvable dependency raises error."""
        # Arrange
        container = DependencyContainer()
        registry = ProcessorRegistry()
        
        @registry.register_processor("test_processor")
        class TestProcessor:
            def __init__(self, missing_dep: ITestDependency):
                self.missing_dep = missing_dep
        
        factory = ProcessorFactory(container, registry)
        
        # Act & Assert
        with pytest.raises(ValueError, match="Cannot resolve dependency 'missing_dep'"):
            factory.create_processor("test_processor")
    
    def test_default_parameter_handling(self):
        """Test handling of default parameters in constructors."""
        # Arrange
        container = DependencyContainer()
        registry = ProcessorRegistry()
        
        @registry.register_processor("test_processor")
        class TestProcessor:
            def __init__(self, required_dep: ITestDependency, 
                        optional_param: str = "default_value"):
                self.required_dep = required_dep
                self.optional_param = optional_param
        
        container.register_transient(ITestDependency, TestDependencyImpl)
        factory = ProcessorFactory(container, registry)
        
        # Act
        processor = factory.create_processor("test_processor")
        
        # Assert
        assert isinstance(processor, TestProcessor)
        assert isinstance(processor.required_dep, TestDependencyImpl)
        assert processor.optional_param == "default_value"


class TestServiceLifetime:
    """Test service lifetime behavior."""
    
    def test_singleton_lifecycle(self):
        """Test singleton service lifecycle."""
        # Arrange
        container = DependencyContainer()
        container.register_singleton(ITestService, TestServiceImpl)
        
        # Act
        service1 = container.get(ITestService)
        service2 = container.get(ITestService)
        
        # Assert
        assert service1 is service2
    
    def test_transient_lifecycle(self):
        """Test transient service lifecycle."""
        # Arrange
        container = DependencyContainer()
        container.register_transient(ITestService, TestServiceImpl)
        
        # Act
        service1 = container.get(ITestService)
        service2 = container.get(ITestService)
        
        # Assert
        assert service1 is not service2
        assert isinstance(service1, TestServiceImpl)
        assert isinstance(service2, TestServiceImpl)


class TestThreadSafety:
    """Test thread safety of the DI container."""
    
    def test_concurrent_singleton_creation(self):
        """Test concurrent access to singleton services."""
        import threading
        import time
        
        # Arrange
        container = DependencyContainer()
        
        class SlowInitService:
            def __init__(self):
                time.sleep(0.1)  # Simulate slow initialization
                self.created_at = time.time()
        
        container.register_singleton(ITestService, SlowInitService)
        
        results = []
        
        def get_service():
            service = container.get(ITestService)
            results.append(service)
        
        # Act
        threads = [threading.Thread(target=get_service) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # Assert
        assert len(results) == 5
        # All results should be the same instance
        assert all(service is results[0] for service in results)
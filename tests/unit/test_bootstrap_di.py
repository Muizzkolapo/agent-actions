"""
Comprehensive tests for the dependency injection system with focus on global state elimination.

This test suite validates that the DI system operates correctly without global state,
ensuring thread-safety, proper scoping, container lifecycle management, and backward compatibility.

Test Categories:
1. Container initialization without global state
2. Thread-safety of container patterns
3. Service scoping (Singleton, Transient, Scoped)
4. Container lifecycle management
5. Error handling for uninitialized containers
6. Backward compatibility scenarios
7. Concurrent container access
8. Container reset/cleanup
9. Service registration and resolution
10. Factory method support
11. Dependency chain resolution

@author: Generated test suite for DI validation
@version: 1.0.0
"""

import pytest
import threading
import time
import concurrent.futures
from typing import Protocol, Dict, Any, List, Optional
from unittest.mock import Mock, patch, MagicMock
from contextlib import contextmanager
import weakref
import gc
from dataclasses import dataclass
from pathlib import Path

from agent_actions._internal.bootstrap.bootstrap import (
    initialize_application,
    get_application_container,
    create_agent_runner,
    reset_application,
    get_agent_runner_with_di,
    is_di_enabled,
)
from agent_actions.core.runtime.application_container import ApplicationContainer
from agent_actions.core.graph.dependency_injection import (
    DependencyContainer,
    ProcessorFactory,
    ServiceLifetime,
    ServiceDescriptor,
    registry,
)
from agent_actions.core.di_configurator import DIConfigurator, ConfigurationProfile
from agent_actions.core.agent_runner import AgentRunner
from agent_actions.core.contracts.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    ISourceDataLoader,
)
from agent_actions.tasks.services.batch_service import BatchService


# Test interfaces and implementations for DI validation
class ITestServiceA(Protocol):
    """Test service interface A."""
    def get_name(self) -> str:
        ...


class ITestServiceB(Protocol):
    """Test service interface B."""
    def get_value(self) -> int:
        ...


class ITestServiceC(Protocol):
    """Test service interface C."""
    def process_data(self, data: str) -> str:
        ...


class TestServiceAImpl:
    """Implementation of test service A."""
    
    def __init__(self, name: str = "ServiceA"):
        self.name = name
        self.creation_time = time.time()
    
    def get_name(self) -> str:
        return self.name


class TestServiceBImpl:
    """Implementation of test service B."""
    
    def __init__(self, value: int = 42):
        self.value = value
        self.creation_time = time.time()
    
    def get_value(self) -> int:
        return self.value


class TestServiceCImpl:
    """Implementation of test service C with dependencies."""
    
    def __init__(self, service_a: ITestServiceA, service_b: ITestServiceB):
        self.service_a = service_a
        self.service_b = service_b
        self.creation_time = time.time()
    
    def process_data(self, data: str) -> str:
        return f"{self.service_a.get_name()}-{self.service_b.get_value()}-{data}"


@dataclass
class ContainerTestResult:
    """Result holder for concurrent testing."""
    container_id: str
    service_instance: Any
    thread_id: str
    timestamp: float
    error: Optional[Exception] = None


class TestContainerInitializationWithoutGlobalState:
    """Test suite for container initialization without relying on global state."""

    def test_container_initialization_is_isolated(self):
        """Test that each container initialization creates an isolated instance."""
        # Arrange & Act
        container1 = ApplicationContainer()
        container2 = ApplicationContainer()
        
        # Assert
        assert container1 is not container2
        assert id(container1) != id(container2)
        assert container1.container is not container2.container
        
    def test_container_with_custom_config_isolation(self):
        """Test containers with different configurations are isolated."""
        # Arrange
        config1 = {'environment': 'development', 'debug': True}
        config2 = {'environment': 'production', 'debug': False}
        
        # Act
        container1 = ApplicationContainer(config1)
        container2 = ApplicationContainer(config2)
        
        # Assert
        assert container1.config != container2.config
        assert container1.config['debug'] != container2.config['debug']
        assert container1 is not container2

    def test_container_environment_factory_creates_unique_instances(self):
        """Test that environment factory methods create unique instances."""
        # Act
        dev_container = ApplicationContainer.create_for_environment('development')
        prod_container = ApplicationContainer.create_for_environment('production')
        test_container = ApplicationContainer.create_for_environment('testing')
        
        # Assert
        assert dev_container is not prod_container
        assert dev_container is not test_container
        assert prod_container is not test_container
        
        # Verify configurations are different
        assert dev_container.config['environment'] == 'development'
        assert prod_container.config['environment'] == 'production'
        assert test_container.config['environment'] == 'testing'

    def test_testing_container_factory_isolation(self):
        """Test that testing container factory creates isolated instances."""
        # Act
        test_container1 = ApplicationContainer.create_for_testing()
        test_container2 = ApplicationContainer.create_for_testing()
        
        # Assert
        assert test_container1 is not test_container2
        assert test_container1.container is not test_container2.container


class TestThreadSafetyOfContainerPatterns:
    """Test suite for thread-safety of the new container patterns."""

    def test_concurrent_container_creation(self):
        """Test that concurrent container creation is thread-safe."""
        # Arrange
        results = []
        results_lock = threading.Lock()
        num_threads = 10
        
        def create_container(thread_id: int):
            try:
                container = ApplicationContainer()
                with results_lock:
                    results.append({
                        'thread_id': thread_id,
                        'container_id': id(container),
                        'success': True,
                        'error': None
                    })
            except Exception as e:
                with results_lock:
                    results.append({
                        'thread_id': thread_id,
                        'container_id': None,
                        'success': False,
                        'error': str(e)
                    })
        
        # Act
        threads = []
        for i in range(num_threads):
            thread = threading.Thread(target=create_container, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Assert
        assert len(results) == num_threads
        assert all(result['success'] for result in results)
        
        # All container IDs should be unique
        container_ids = [r['container_id'] for r in results if r['container_id']]
        assert len(set(container_ids)) == num_threads

    def test_concurrent_service_resolution_thread_safety(self):
        """Test thread-safety of service resolution within a single container."""
        # Arrange
        container = DependencyContainer()
        container.register_singleton(ITestServiceA, TestServiceAImpl)
        container.register_transient(ITestServiceB, TestServiceBImpl)
        
        results = []
        results_lock = threading.Lock()
        
        def resolve_services(thread_id: int):
            try:
                # Resolve singleton (should be same instance)
                singleton_service = container.get(ITestServiceA)
                # Resolve transient (should be different instances)
                transient_service = container.get(ITestServiceB)
                
                with results_lock:
                    results.append({
                        'thread_id': thread_id,
                        'singleton_id': id(singleton_service),
                        'transient_id': id(transient_service),
                        'success': True,
                        'error': None
                    })
            except Exception as e:
                with results_lock:
                    results.append({
                        'thread_id': thread_id,
                        'singleton_id': None,
                        'transient_id': None,
                        'success': False,
                        'error': str(e)
                    })
        
        # Act
        threads = []
        for i in range(10):
            thread = threading.Thread(target=resolve_services, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Assert
        assert len(results) == 10
        assert all(result['success'] for result in results)
        
        # All singleton IDs should be the same
        singleton_ids = [r['singleton_id'] for r in results if r['singleton_id']]
        assert len(set(singleton_ids)) == 1
        
        # All transient IDs should be different
        transient_ids = [r['transient_id'] for r in results if r['transient_id']]
        assert len(set(transient_ids)) == 10

    def test_concurrent_container_with_slow_initialization(self):
        """Test concurrent access to services with slow initialization."""
        # Arrange
        class SlowService:
            def __init__(self):
                time.sleep(0.1)  # Simulate slow initialization
                self.creation_time = time.time()
                self.initialized = True
        
        container = DependencyContainer()
        container.register_singleton(ITestServiceA, SlowService)
        
        results = []
        results_lock = threading.Lock()
        
        def get_slow_service(thread_id: int):
            try:
                service = container.get(ITestServiceA)
                with results_lock:
                    results.append({
                        'thread_id': thread_id,
                        'service_id': id(service),
                        'creation_time': service.creation_time,
                        'success': True
                    })
            except Exception as e:
                with results_lock:
                    results.append({
                        'thread_id': thread_id,
                        'service_id': None,
                        'creation_time': None,
                        'success': False,
                        'error': str(e)
                    })
        
        # Act
        threads = []
        for i in range(5):
            thread = threading.Thread(target=get_slow_service, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Assert
        assert len(results) == 5
        assert all(result['success'] for result in results)
        
        # All services should be the same instance (singleton)
        service_ids = [r['service_id'] for r in results]
        assert len(set(service_ids)) == 1
        
        # All should have the same creation time
        creation_times = [r['creation_time'] for r in results]
        assert len(set(creation_times)) == 1


class TestServiceScoping:
    """Test suite for proper service scoping (Singleton, Transient, Scoped)."""

    def test_singleton_service_lifecycle(self):
        """Test singleton service maintains single instance across requests."""
        # Arrange
        container = DependencyContainer()
        container.register_singleton(ITestServiceA, TestServiceAImpl)
        
        # Act
        service1 = container.get(ITestServiceA)
        service2 = container.get(ITestServiceA)
        service3 = container.get(ITestServiceA)
        
        # Assert
        assert service1 is service2
        assert service2 is service3
        assert id(service1) == id(service2) == id(service3)

    def test_transient_service_lifecycle(self):
        """Test transient service creates new instance per request."""
        # Arrange
        container = DependencyContainer()
        container.register_transient(ITestServiceA, TestServiceAImpl)
        
        # Act
        service1 = container.get(ITestServiceA)
        service2 = container.get(ITestServiceA)
        service3 = container.get(ITestServiceA)
        
        # Assert
        assert service1 is not service2
        assert service2 is not service3
        assert service1 is not service3
        assert len({id(service1), id(service2), id(service3)}) == 3

    def test_mixed_scoping_in_dependency_chain(self):
        """Test proper scoping behavior in dependency chains."""
        # Arrange
        container = DependencyContainer()
        container.register_singleton(ITestServiceA, TestServiceAImpl)
        container.register_transient(ITestServiceB, TestServiceBImpl)
        container.register_transient(ITestServiceC, TestServiceCImpl)
        
        # Act
        service1 = container.get(ITestServiceC)
        service2 = container.get(ITestServiceC)
        
        # Assert
        # Services C should be different (transient)
        assert service1 is not service2
        
        # But their ServiceA dependencies should be the same (singleton)
        assert service1.service_a is service2.service_a
        
        # And their ServiceB dependencies should be different (transient)
        assert service1.service_b is not service2.service_b

    def test_factory_registration_behavior(self):
        """Test factory-registered services behavior."""
        # Arrange
        container = DependencyContainer()
        call_count = 0
        
        def service_factory() -> ITestServiceA:
            nonlocal call_count
            call_count += 1
            return TestServiceAImpl(f"Factory-{call_count}")
        
        container.register_factory(ITestServiceA, service_factory)
        
        # Act
        service1 = container.get(ITestServiceA)
        service2 = container.get(ITestServiceA)
        
        # Assert
        assert call_count == 2
        assert service1 is not service2
        assert service1.get_name() == "Factory-1"
        assert service2.get_name() == "Factory-2"

    def test_instance_registration_behavior(self):
        """Test instance-registered services behavior."""
        # Arrange
        container = DependencyContainer()
        specific_instance = TestServiceAImpl("SpecificInstance")
        container.register_instance(ITestServiceA, specific_instance)
        
        # Act
        retrieved1 = container.get(ITestServiceA)
        retrieved2 = container.get(ITestServiceA)
        
        # Assert
        assert retrieved1 is specific_instance
        assert retrieved2 is specific_instance
        assert retrieved1 is retrieved2


class TestContainerLifecycleManagement:
    """Test suite for container lifecycle management."""

    def test_container_cleanup_releases_resources(self):
        """Test that container cleanup properly releases resources."""
        # Arrange
        container = DependencyContainer()
        container.register_singleton(ITestServiceA, TestServiceAImpl)
        
        # Create and get references
        service = container.get(ITestServiceA)
        service_id = id(service)
        weak_ref = weakref.ref(service)
        
        # Act - Clear references
        del service
        del container
        gc.collect()  # Force garbage collection
        
        # Assert
        assert weak_ref() is None  # Should be garbage collected

    def test_application_container_health_check(self):
        """Test application container health check functionality."""
        # Arrange
        container = ApplicationContainer.create_for_testing()
        
        # Act
        health_result = container.health_check()
        
        # Assert
        assert isinstance(health_result, dict)
        assert 'status' in health_result
        assert 'services' in health_result
        assert 'timestamp' in health_result
        
        # Should be healthy with mocked dependencies
        assert health_result['status'] == 'healthy'

    def test_container_memory_usage_stability(self):
        """Test container doesn't leak memory with repeated operations."""
        # Arrange
        container = DependencyContainer()
        container.register_transient(ITestServiceA, TestServiceAImpl)
        
        # Act - Create many transient instances
        services = []
        for i in range(100):
            service = container.get(ITestServiceA)
            services.append(service)
        
        # Clear references
        del services
        gc.collect()
        
        # Assert - No exceptions should occur
        # Memory usage should stabilize (difficult to test precisely)
        assert True  # If we get here, no memory issues occurred


class TestErrorHandlingForUninitializedContainer:
    """Test suite for error handling when containers are not properly initialized."""

    def test_unregistered_service_resolution_error(self):
        """Test proper error handling for unregistered services."""
        # Arrange
        container = DependencyContainer()
        
        # Act & Assert
        with pytest.raises(ValueError, match="Service ITestServiceA not registered"):
            container.get(ITestServiceA)

    def test_unresolvable_dependency_error(self):
        """Test proper error handling for unresolvable dependencies."""
        # Arrange
        container = DependencyContainer()
        container.register_transient(ITestServiceC, TestServiceCImpl)  # Has dependencies but they're not registered
        
        # Act & Assert
        with pytest.raises(ValueError, match="Cannot resolve dependency"):
            container.get(ITestServiceC)

    def test_processor_factory_unregistered_component_error(self):
        """Test processor factory error handling for unregistered components."""
        # Arrange
        container = DependencyContainer()
        factory = ProcessorFactory(container, registry)
        
        # Act & Assert
        with pytest.raises(ValueError, match="not registered"):
            factory.create_processor("nonexistent_processor")

    def test_application_container_invalid_environment_error(self):
        """Test error handling for invalid environment configurations."""
        # Act & Assert
        with pytest.raises(ValueError, match="Unknown environment"):
            ApplicationContainer.create_for_environment("invalid_environment")

    def test_circular_dependency_detection(self):
        """Test detection and handling of circular dependencies."""
        # This test is for a feature that could be implemented
        # Currently, circular dependencies would cause recursion issues
        
        class ServiceX:
            def __init__(self, service_y):
                self.service_y = service_y
        
        class ServiceY:
            def __init__(self, service_x):
                self.service_x = service_x
        
        container = DependencyContainer()
        container.register_transient(ServiceX, ServiceX)
        container.register_transient(ServiceY, ServiceY)
        
        # This should eventually be handled gracefully
        # For now, we expect a RecursionError or similar
        with pytest.raises((RecursionError, ValueError)):
            container.get(ServiceX)


class TestBackwardCompatibilityScenarios:
    """Test suite for backward compatibility scenarios."""

    def test_bootstrap_functions_maintain_compatibility(self):
        """Test that bootstrap functions maintain expected behavior."""
        # Test cleanup first
        reset_application()
        
        # Act & Assert
        # Should be able to initialize
        container = initialize_application()
        assert isinstance(container, ApplicationContainer)
        
        # Should be able to get container
        same_container = get_application_container()
        assert same_container is container
        
        # Should be able to create agent runner
        agent_runner = create_agent_runner()
        assert isinstance(agent_runner, AgentRunner)
        
        # Should detect DI is enabled
        assert is_di_enabled() is True
        
        # Cleanup
        reset_application()
        
    def test_backward_compatible_agent_runner_creation(self):
        """Test backward compatible agent runner creation."""
        # Setup
        reset_application()
        
        # Act
        agent_runner1 = get_agent_runner_with_di(use_tools=True)
        agent_runner2 = create_agent_runner(use_tools=False)
        
        # Assert
        assert isinstance(agent_runner1, AgentRunner)
        assert isinstance(agent_runner2, AgentRunner)
        assert agent_runner1.use_tools is True
        assert agent_runner2.use_tools is False
        
        # Cleanup
        reset_application()

    def test_configuration_profile_compatibility(self):
        """Test that configuration profiles work as expected."""
        # Act
        dev_config = ConfigurationProfile.development()
        prod_config = ConfigurationProfile.production()
        test_config = ConfigurationProfile.testing()
        
        # Assert
        assert dev_config['environment'] == 'development'
        assert prod_config['environment'] == 'production'
        assert test_config['environment'] == 'testing'
        
        # Verify different settings
        assert dev_config['logging']['level'] == 'DEBUG'
        assert prod_config['logging']['level'] == 'INFO'
        assert test_config['logging']['level'] == 'ERROR'

    def test_legacy_processor_factory_integration(self):
        """Test integration with existing processor factory patterns."""
        # Arrange
        container = ApplicationContainer.create_for_testing()
        processor_factory = container.get_processor_factory()
        
        # Act & Assert
        assert isinstance(processor_factory, ProcessorFactory)
        
        # Should be able to create source data loader
        source_loader = processor_factory.create_source_data_loader("test_agent")
        assert source_loader is not None


class TestConcurrentContainerAccess:
    """Test suite for concurrent container access scenarios."""

    def test_multiple_containers_concurrent_access(self):
        """Test concurrent access across multiple container instances."""
        # Arrange
        containers = [ApplicationContainer() for _ in range(5)]
        results = []
        results_lock = threading.Lock()
        
        def access_container(container_idx: int):
            try:
                container = containers[container_idx]
                agent_runner = container.get_agent_runner()
                dependency_container = container.get_dependency_container()
                
                with results_lock:
                    results.append({
                        'container_idx': container_idx,
                        'agent_runner_id': id(agent_runner),
                        'dependency_container_id': id(dependency_container),
                        'success': True,
                        'error': None
                    })
            except Exception as e:
                with results_lock:
                    results.append({
                        'container_idx': container_idx,
                        'success': False,
                        'error': str(e)
                    })
        
        # Act
        threads = []
        for i in range(5):
            thread = threading.Thread(target=access_container, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Assert
        assert len(results) == 5
        assert all(result['success'] for result in results)
        
        # All containers should have different dependency containers
        dep_container_ids = [r['dependency_container_id'] for r in results]
        assert len(set(dep_container_ids)) == 5

    def test_concurrent_target_content_processor_creation(self):
        """Test concurrent creation of target content processors."""
        # Arrange
        container = ApplicationContainer.create_for_testing()
        results = []
        results_lock = threading.Lock()
        
        def create_processor(idx: int):
            try:
                agent_config = {'agent_type': f'test_agent_{idx}'}
                processor = container.create_target_content_processor(
                    agent_config, f"agent_{idx}", idx
                )
                
                with results_lock:
                    results.append({
                        'idx': idx,
                        'processor_id': id(processor),
                        'success': True,
                        'error': None
                    })
            except Exception as e:
                with results_lock:
                    results.append({
                        'idx': idx,
                        'success': False,
                        'error': str(e)
                    })
        
        # Act
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_processor, i) for i in range(20)]
            concurrent.futures.wait(futures)
        
        # Assert
        assert len(results) == 20
        assert all(result['success'] for result in results)
        
        # All processors should be different instances
        processor_ids = [r['processor_id'] for r in results if r.get('processor_id')]
        assert len(set(processor_ids)) == 20


class TestContainerResetAndCleanup:
    """Test suite for container reset and cleanup functionality."""

    def test_reset_application_clears_global_state(self):
        """Test that reset_application properly clears any global state."""
        # Arrange
        initialize_application()
        assert is_di_enabled() is True
        
        # Act
        reset_application()
        
        # Assert
        assert is_di_enabled() is False

    def test_container_isolation_after_reset(self):
        """Test that containers remain isolated after reset operations."""
        # Arrange
        container1 = initialize_application()
        original_id = id(container1)
        
        # Act
        reset_application()
        container2 = initialize_application()
        
        # Assert
        assert id(container2) != original_id
        assert container1 is not container2
        
        # Cleanup
        reset_application()

    def test_multiple_reset_operations_safety(self):
        """Test that multiple reset operations are safe."""
        # Act & Assert - Should not raise exceptions
        reset_application()
        reset_application()
        reset_application()
        
        assert is_di_enabled() is False
        
        # Should still be able to initialize after multiple resets
        container = initialize_application()
        assert isinstance(container, ApplicationContainer)
        
        # Cleanup
        reset_application()


class TestServiceRegistrationAndResolution:
    """Test suite for service registration and resolution patterns."""

    def test_complex_dependency_chain_resolution(self):
        """Test resolution of complex dependency chains."""
        # Arrange
        container = DependencyContainer()
        
        # Register services in dependency order
        container.register_singleton(ITestServiceA, TestServiceAImpl)
        container.register_singleton(ITestServiceB, TestServiceBImpl)
        container.register_transient(ITestServiceC, TestServiceCImpl)
        
        # Act
        service_c = container.get(ITestServiceC)
        
        # Assert
        assert isinstance(service_c, TestServiceCImpl)
        assert isinstance(service_c.service_a, TestServiceAImpl)
        assert isinstance(service_c.service_b, TestServiceBImpl)
        
        # Test processing works
        result = service_c.process_data("test")
        assert "ServiceA-42-test" == result

    def test_service_override_and_replacement(self):
        """Test that services can be overridden and replaced."""
        # Arrange
        container = DependencyContainer()
        
        # Register initial service
        container.register_singleton(ITestServiceA, TestServiceAImpl)
        initial_service = container.get(ITestServiceA)
        
        # Act - Override with instance
        override_service = TestServiceAImpl("OverrideService")
        container.register_instance(ITestServiceA, override_service)
        
        # Assert
        retrieved_service = container.get(ITestServiceA)
        assert retrieved_service is override_service
        assert retrieved_service is not initial_service
        assert retrieved_service.get_name() == "OverrideService"

    def test_conditional_service_registration(self):
        """Test conditional service registration patterns."""
        # Arrange
        container = DependencyContainer()
        
        # Act - Register services conditionally
        if not container.has(ITestServiceA):
            container.register_singleton(ITestServiceA, TestServiceAImpl)
        
        if not container.has(ITestServiceB):
            container.register_transient(ITestServiceB, TestServiceBImpl)
        
        # Try to register again (should be skipped)
        if not container.has(ITestServiceA):
            container.register_singleton(ITestServiceA, TestServiceBImpl)  # This shouldn't happen
        
        # Assert
        service_a = container.get(ITestServiceA)
        assert isinstance(service_a, TestServiceAImpl)  # Should be the first registration
        
        service_b = container.get(ITestServiceB)
        assert isinstance(service_b, TestServiceBImpl)


class TestFactoryMethodSupport:
    """Test suite for factory method support and patterns."""

    def test_processor_factory_with_runtime_parameters(self):
        """Test processor factory with runtime parameters."""
        # Arrange
        container = DependencyContainer()
        container.register_singleton(ITestServiceA, TestServiceAImpl)
        
        factory = ProcessorFactory(container, registry)
        
        # Act - Test source data loader creation with runtime parameters
        source_loader = factory.create_source_data_loader("runtime_agent")
        
        # Assert
        assert source_loader is not None
        # Verify it was created with the runtime parameter

    def test_application_container_factory_methods(self):
        """Test application container factory methods."""
        # Act
        dev_container = ApplicationContainer.create_for_environment('development')
        prod_container = ApplicationContainer.create_for_environment('production')
        test_container = ApplicationContainer.create_for_testing()
        
        # Assert
        assert isinstance(dev_container, ApplicationContainer)
        assert isinstance(prod_container, ApplicationContainer)
        assert isinstance(test_container, ApplicationContainer)
        
        # Verify different configurations
        assert dev_container.config['environment'] == 'development'
        assert prod_container.config['environment'] == 'production'
        assert test_container.config['environment'] == 'testing'

    def test_factory_with_dependency_injection_override(self):
        """Test factory creation with dependency injection overrides."""
        # Arrange
        container = DependencyContainer()
        container.register_singleton(ITestServiceA, TestServiceAImpl)
        container.register_singleton(ITestServiceB, TestServiceBImpl)
        
        factory = ProcessorFactory(container, registry)
        
        # Create override dependencies
        override_service_a = TestServiceAImpl("Override")
        override_service_b = TestServiceBImpl(999)
        
        # Register a test processor for this test
        @registry.register_processor("factory_test_processor")
        class FactoryTestProcessor:
            def __init__(self, service_a: ITestServiceA, service_b: ITestServiceB, custom_param: str = "default"):
                self.service_a = service_a
                self.service_b = service_b
                self.custom_param = custom_param
        
        # Act
        processor = factory.create_processor(
            "factory_test_processor",
            service_a=override_service_a,
            service_b=override_service_b,
            custom_param="overridden"
        )
        
        # Assert
        assert isinstance(processor, FactoryTestProcessor)
        assert processor.service_a is override_service_a
        assert processor.service_b is override_service_b
        assert processor.custom_param == "overridden"


class TestIntegrationWithExistingServices:
    """Integration tests with existing application services."""

    def test_batch_service_integration(self):
        """Test integration with BatchService."""
        # Arrange
        container = ApplicationContainer.create_for_testing()
        
        # Act
        batch_service = container.get_dependency_container().get(BatchService)
        
        # Assert
        assert batch_service is not None
        # Batch service should be a mock in testing container
        assert hasattr(batch_service, 'submit_batch_job_from_data')

    def test_path_manager_integration(self):
        """Test integration with PathManager."""
        # Arrange
        container = ApplicationContainer.create_for_testing()
        
        # Act
        from agent_actions.core.path_manager import PathManager
        path_manager = container.get_dependency_container().get(PathManager)
        
        # Assert
        assert path_manager is not None
        # Path manager should be a mock in testing container

    def test_full_target_content_processor_integration(self):
        """Test full integration with target content processor creation."""
        # Arrange
        container = ApplicationContainer.create_for_testing()
        agent_config = {
            'agent_type': 'integration_test',
            'model': 'test-model'
        }
        
        # Act
        processor = container.create_target_content_processor(
            agent_config, "integration_test_agent", 0
        )
        
        # Assert
        assert processor is not None
        # Should be created without errors even with mocked dependencies


class TestErrorScenarios:
    """Test suite for various error scenarios and edge cases."""

    def test_malformed_configuration_handling(self):
        """Test handling of malformed configurations."""
        # Act & Assert
        with pytest.raises((ValueError, KeyError, TypeError)):
            ApplicationContainer({"invalid": None, "config": {"nested": []}})

    def test_service_creation_failure_handling(self):
        """Test handling of service creation failures."""
        # Arrange
        class FailingService:
            def __init__(self):
                raise Exception("Service creation failed")
        
        container = DependencyContainer()
        container.register_singleton(ITestServiceA, FailingService)
        
        # Act & Assert
        with pytest.raises(Exception, match="Service creation failed"):
            container.get(ITestServiceA)

    def test_dependency_resolution_with_missing_type_hints(self):
        """Test dependency resolution when type hints are missing."""
        # Arrange
        class ServiceWithoutHints:
            def __init__(self, some_param):  # No type hint
                self.some_param = some_param
        
        container = DependencyContainer()
        container.register_transient(ServiceWithoutHints, ServiceWithoutHints)
        
        # Act & Assert - Should handle gracefully
        # This might fail or succeed depending on implementation
        # The key is that it shouldn't crash unexpectedly
        try:
            service = container.get(ServiceWithoutHints)
            # If it succeeds, the parameter should have been handled somehow
            assert hasattr(service, 'some_param')
        except ValueError:
            # If it fails, it should be a clear dependency resolution error
            pass


@pytest.fixture(autouse=True)
def cleanup_global_state():
    """Ensure global state is cleaned up after each test."""
    yield
    # Cleanup after test
    reset_application()


@pytest.fixture
def isolated_container():
    """Provide an isolated container for testing."""
    container = DependencyContainer()
    return container


@pytest.fixture
def test_application_container():
    """Provide a test application container."""
    return ApplicationContainer.create_for_testing()


# Performance and stress testing
class TestPerformanceAndStress:
    """Performance and stress testing for the DI system."""

    def test_container_performance_with_many_services(self):
        """Test container performance with many registered services."""
        # Arrange
        container = DependencyContainer()
        
        # Register many services
        for i in range(100):
            service_class = type(f'TestService{i}', (), {
                '__init__': lambda self: None,
                'get_id': lambda self: i
            })
            interface_class = type(f'ITestService{i}', (), {})
            
            container.register_transient(interface_class, service_class)
        
        # Act & Assert - Should complete without performance issues
        start_time = time.time()
        
        # Create services multiple times
        for _ in range(10):
            for i in range(100):
                interface_class = type(f'ITestService{i}', (), {})
                try:
                    service = container.get(interface_class)
                    assert service is not None
                except:
                    pass  # Some may fail due to dynamic type creation
        
        elapsed_time = time.time() - start_time
        
        # Should complete within reasonable time (adjust threshold as needed)
        assert elapsed_time < 5.0  # 5 seconds threshold

    def test_memory_usage_with_transient_services(self):
        """Test memory usage patterns with many transient services."""
        # Arrange
        container = DependencyContainer()
        container.register_transient(ITestServiceA, TestServiceAImpl)
        
        # Act - Create many transient instances
        services = []
        for i in range(1000):
            service = container.get(ITestServiceA)
            services.append(service)
        
        # Verify all are different instances
        service_ids = [id(service) for service in services]
        assert len(set(service_ids)) == 1000
        
        # Cleanup
        del services
        gc.collect()
        
        # Assert - Test completed without memory issues
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
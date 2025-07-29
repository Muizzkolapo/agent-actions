"""
Dependency Injection Framework for Agent Actions.

This module provides a lightweight dependency injection container and registry
for managing processor dependencies and improving testability.
"""

from typing import Dict, Type, Any, TypeVar, Callable, Optional, get_type_hints
import inspect
import threading
from abc import ABC, abstractmethod

T = TypeVar('T')


class ServiceLifetime:
    """Service lifetime constants."""
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


class ServiceDescriptor:
    """Describes how a service should be created and managed."""
    
    def __init__(self, service_type: Type, implementation: Type, lifetime: str):
        self.service_type = service_type
        self.implementation = implementation
        self.lifetime = lifetime


class DependencyContainer:
    """Lightweight dependency injection container."""
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._factories: Dict[Type, Callable] = {}
        self._instances: Dict[Type, Any] = {}
        self._lock = threading.Lock()
    
    def register_singleton(self, interface: Type[T], implementation: Type[T]) -> 'DependencyContainer':
        """Register a singleton service."""
        self._services[interface] = ServiceDescriptor(interface, implementation, ServiceLifetime.SINGLETON)
        return self
    
    def register_transient(self, interface: Type[T], implementation: Type[T]) -> 'DependencyContainer':
        """Register a transient service."""
        self._services[interface] = ServiceDescriptor(interface, implementation, ServiceLifetime.TRANSIENT)
        return self
    
    def register_factory(self, interface: Type[T], factory: Callable[[], T]) -> 'DependencyContainer':
        """Register a factory function."""
        self._factories[interface] = factory
        return self
    
    def register_instance(self, interface: Type[T], instance: T) -> 'DependencyContainer':
        """Register a specific instance."""
        with self._lock:
            self._instances[interface] = instance
        return self
    
    def get(self, interface: Type[T]) -> T:
        """Resolve a dependency."""
        # Check for pre-registered instances
        if interface in self._instances:
            return self._instances[interface]
        
        # Check for factories
        if interface in self._factories:
            return self._factories[interface]()
        
        # Check for registered services
        if interface in self._services:
            descriptor = self._services[interface]
            
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                with self._lock:
                    if interface not in self._instances:
                        self._instances[interface] = self._create_instance(descriptor.implementation)
                    return self._instances[interface]
            else:
                return self._create_instance(descriptor.implementation)
        
        raise ValueError(f"Service {interface.__name__} not registered")
    
    def has(self, interface: Type) -> bool:
        """Check if a service is registered."""
        return (interface in self._services or 
                interface in self._factories or 
                interface in self._instances)
    
    def _create_instance(self, cls: Type[T]) -> T:
        """Create instance with dependency resolution."""
        signature = inspect.signature(cls.__init__)
        type_hints = get_type_hints(cls.__init__)
        
        init_kwargs = {}
        for param_name, param in signature.parameters.items():
            if param_name == 'self':
                continue
                
            param_type = type_hints.get(param_name)
            if param_type and self.has(param_type):
                init_kwargs[param_name] = self.get(param_type)
            elif param.default != inspect.Parameter.empty:
                init_kwargs[param_name] = param.default
            else:
                raise ValueError(f"Cannot resolve dependency '{param_name}' for {cls.__name__}")
        
        return cls(**init_kwargs)


class ProcessorRegistry:
    """Registry for managing processor implementations."""
    
    def __init__(self):
        self._processors: Dict[str, Type] = {}
        self._loaders: Dict[str, Type] = {}
        self._generators: Dict[str, Type] = {}
        self._services: Dict[str, Type] = {}
    
    def register_processor(self, name: str):
        """Decorator to register a processor."""
        def decorator(cls: Type):
            self._processors[name] = cls
            return cls
        return decorator
    
    def register_loader(self, name: str):
        """Decorator to register a data loader."""
        def decorator(cls: Type):
            self._loaders[name] = cls
            return cls
        return decorator
    
    def register_generator(self, name: str):
        """Decorator to register a generator."""
        def decorator(cls: Type):
            self._generators[name] = cls
            return cls
        return decorator
    
    def register_service(self, name: str):
        """Decorator to register a service."""
        def decorator(cls: Type):
            self._services[name] = cls
            return cls
        return decorator
    
    def get_processor(self, name: str) -> Type:
        """Get a processor class by name."""
        if name not in self._processors:
            raise ValueError(f"Processor '{name}' not registered")
        return self._processors[name]
    
    def get_loader(self, name: str) -> Type:
        """Get a loader class by name."""
        if name not in self._loaders:
            raise ValueError(f"Loader '{name}' not registered")
        return self._loaders[name]
    
    def get_generator(self, name: str) -> Type:
        """Get a generator class by name."""
        if name not in self._generators:
            raise ValueError(f"Generator '{name}' not registered")
        return self._generators[name]
    
    def get_service(self, name: str) -> Type:
        """Get a service class by name."""
        if name not in self._services:
            raise ValueError(f"Service '{name}' not registered")
        return self._services[name]
    
    def list_processors(self) -> Dict[str, Type]:
        """List all registered processors."""
        return self._processors.copy()
    
    def list_loaders(self) -> Dict[str, Type]:
        """List all registered loaders."""
        return self._loaders.copy()
    
    def list_generators(self) -> Dict[str, Type]:
        """List all registered generators."""
        return self._generators.copy()
    
    def list_services(self) -> Dict[str, Type]:
        """List all registered services."""
        return self._services.copy()


class ProcessorFactory:
    """Factory for creating processors with dependency injection."""
    
    def __init__(self, container: DependencyContainer, registry: ProcessorRegistry):
        self.container = container
        self.registry = registry
    
    def create_processor(self, name: str, **kwargs) -> Any:
        """Create a processor instance with injected dependencies."""
        processor_cls = self.registry.get_processor(name)
        return self._create_with_dependencies(processor_cls, **kwargs)
    
    def create_loader(self, name: str, **kwargs) -> Any:
        """Create a loader instance with injected dependencies."""
        loader_cls = self.registry.get_loader(name)
        return self._create_with_dependencies(loader_cls, **kwargs)
    
    def create_generator(self, name: str, **kwargs) -> Any:
        """Create a generator instance with injected dependencies."""
        generator_cls = self.registry.get_generator(name)
        return self._create_with_dependencies(generator_cls, **kwargs)
    
    def create_service(self, name: str, **kwargs) -> Any:
        """Create a service instance with injected dependencies."""
        service_cls = self.registry.get_service(name)
        return self._create_with_dependencies(service_cls, **kwargs)
    
    def _create_with_dependencies(self, cls: Type, **override_kwargs) -> Any:
        """Create instance with automatic dependency resolution."""
        signature = inspect.signature(cls.__init__)
        type_hints = get_type_hints(cls.__init__)
        
        init_kwargs = {}
        
        for param_name, param in signature.parameters.items():
            if param_name == 'self':
                continue
                
            # Use override if provided
            if param_name in override_kwargs:
                init_kwargs[param_name] = override_kwargs[param_name]
                continue
            
            # Try to resolve from container
            param_type = type_hints.get(param_name)
            if param_type and self.container.has(param_type):
                init_kwargs[param_name] = self.container.get(param_type)
            elif param.default != inspect.Parameter.empty:
                # Use default value
                init_kwargs[param_name] = param.default
            else:
                raise ValueError(f"Cannot resolve dependency '{param_name}' for {cls.__name__}")
        
        return cls(**init_kwargs)
    
    def create_source_data_loader(self, agent_name: str):
        """Create a SourceDataLoader with the required agent_name parameter."""
        from ..processors.source_processor.source_data_loader import SourceDataLoader
        from ..core.path_manager import PathManager
        
        path_manager = self.container.get(PathManager)
        return SourceDataLoader(agent_name=agent_name, path_manager=path_manager)


# Global registry instance
registry = ProcessorRegistry()
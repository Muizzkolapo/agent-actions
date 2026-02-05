"""
Dependency Injection Framework for Agent Actions.

This module provides a lightweight dependency injection container and registry
for managing processor dependencies and improving testability.
"""

from typing import Dict, Type, Any, TypeVar, Callable, get_type_hints
import inspect
import threading
from dataclasses import dataclass
from enum import Enum

from agent_actions.errors import DependencyError, ConfigurationError

T = TypeVar("T")


class ServiceLifetime(str, Enum):
    """Service lifetime constants."""

    SINGLETON = "singleton"
    TRANSIENT = "transient"

    @classmethod
    def is_valid(cls, lifetime: str) -> bool:
        """Check if a lifetime value is valid."""
        return lifetime in (cls.SINGLETON.value, cls.TRANSIENT.value)


@dataclass
class ServiceDescriptor:
    """Describes how a service should be created and managed."""

    service_type: Type
    implementation: Type
    lifetime: ServiceLifetime


class DependencyContainer:
    """Lightweight dependency injection container."""

    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._factories: Dict[Type, Callable] = {}
        self._instances: Dict[Type, Any] = {}
        self._lock = threading.Lock()

    def register_singleton(
        self, interface: Type[T], implementation: Type[T]
    ) -> "DependencyContainer":
        """Register a singleton service."""
        self._services[interface] = ServiceDescriptor(
            interface, implementation, ServiceLifetime.SINGLETON
        )
        return self

    def register_transient(
        self, interface: Type[T], implementation: Type[T]
    ) -> "DependencyContainer":
        """Register a transient service."""
        self._services[interface] = ServiceDescriptor(
            interface, implementation, ServiceLifetime.TRANSIENT
        )
        return self

    def register_factory(
        self, interface: Type[T], factory: Callable[[], T]
    ) -> "DependencyContainer":
        """Register a factory function."""
        self._factories[interface] = factory
        return self

    def register_instance(self, interface: Type[T], instance: T) -> "DependencyContainer":
        """Register a specific instance."""
        with self._lock:
            self._instances[interface] = instance
        return self

    def get(self, interface: Type[T]) -> T:
        """Resolve a dependency."""
        if interface in self._instances:
            return self._instances[interface]
        if interface in self._factories:
            return self._factories[interface]()
        if interface in self._services:
            descriptor = self._services[interface]
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                with self._lock:
                    if interface not in self._instances:
                        instance = self._create_instance(descriptor.implementation)
                        self._instances[interface] = instance
                    return self._instances[interface]
            return self._create_instance(descriptor.implementation)

        raise DependencyError(
            f"DependencyContainer: Service {interface.__name__} not found",
            {"interface": interface.__name__, "operation": "get_service"},
        )

    def has(self, interface: Type) -> bool:
        """Check if a service is registered."""
        return (
            interface in self._services
            or interface in self._factories
            or interface in self._instances
        )

    def _create_instance(self, cls: Type[T]) -> T:
        """Create instance with dependency resolution."""
        signature = inspect.signature(cls.__init__)
        type_hints = get_type_hints(cls.__init__)
        init_kwargs = {}
        for param_name, param in signature.parameters.items():
            if param_name == "self" or param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            param_type = type_hints.get(param_name)
            if param_type and self.has(param_type):
                init_kwargs[param_name] = self.get(param_type)
            elif param.default != inspect.Parameter.empty:
                init_kwargs[param_name] = param.default
            else:
                raise DependencyError(
                    f"{cls.__name__}: Missing required dependency {param_name}",
                    {
                        "param_name": param_name,
                        "class": cls.__name__,
                        "operation": "_create_instance",
                    },
                )
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
            raise ConfigurationError(
                f"Processor '{name}' not registered",
                context={"processor_name": name, "operation": "get_processor"},
            )
        return self._processors[name]

    def get_loader(self, name: str) -> Type:
        """Get a loader class by name."""
        if name not in self._loaders:
            raise ConfigurationError(
                f"Loader '{name}' not registered",
                context={"loader_name": name, "operation": "get_loader"},
            )
        return self._loaders[name]

    def get_generator(self, name: str) -> Type:
        """Get a generator class by name."""
        if name not in self._generators:
            raise ConfigurationError(
                f"Generator '{name}' not registered",
                context={"generator_name": name, "operation": "get_generator"},
            )
        return self._generators[name]

    def get_service(self, name: str) -> Type:
        """Get a service class by name."""
        if name not in self._services:
            raise ConfigurationError(
                f"Service '{name}' not registered",
                context={"service_name": name, "operation": "get_service"},
            )
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

    def __init__(
        self,
        container: DependencyContainer,
        processor_registry: ProcessorRegistry,
    ):
        self.container = container
        self.registry = processor_registry

    def create_processor(self, processor_name: str, **kwargs) -> Any:
        """Create a processor instance with injected dependencies."""
        processor_cls = self.registry.get_processor(processor_name)
        return self._create_with_dependencies(processor_cls, **kwargs)

    def create_loader(self, loader_name: str, **kwargs) -> Any:
        """Create a loader instance with injected dependencies."""
        loader_cls = self.registry.get_loader(loader_name)
        return self._create_with_dependencies(loader_cls, **kwargs)

    def create_generator(self, generator_name: str, **kwargs) -> Any:
        """Create a generator instance with injected dependencies."""
        generator_cls = self.registry.get_generator(generator_name)
        return self._create_with_dependencies(generator_cls, **kwargs)

    def create_service(self, service_name: str, **kwargs) -> Any:
        """Create a service instance with injected dependencies."""
        service_cls = self.registry.get_service(service_name)
        return self._create_with_dependencies(service_cls, **kwargs)

    def _create_with_dependencies(self, cls: Type, **override_kwargs) -> Any:
        """Create instance with automatic dependency resolution."""
        signature = inspect.signature(cls.__init__)
        type_hints = get_type_hints(cls.__init__)
        init_kwargs = {}
        for param_name, param in signature.parameters.items():
            if param_name == "self":
                continue
            if param_name in override_kwargs:
                init_kwargs[param_name] = override_kwargs[param_name]
                continue
            param_type = type_hints.get(param_name)
            if param_type and self.container.has(param_type):
                init_kwargs[param_name] = self.container.get(param_type)
            elif param.default != inspect.Parameter.empty:
                init_kwargs[param_name] = param.default
            else:
                raise DependencyError(
                    f"{cls.__name__}: Missing required dependency {param_name}",
                    {
                        "param_name": param_name,
                        "class": cls.__name__,
                        "operation": "_create_with_dependencies",
                    },
                )
        return cls(**init_kwargs)


registry = ProcessorRegistry()

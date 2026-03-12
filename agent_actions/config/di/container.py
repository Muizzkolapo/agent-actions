"""Lightweight dependency injection framework for agent-actions."""

import inspect
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar, get_type_hints

from agent_actions.errors import ConfigurationError, DependencyError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceLifetime(StrEnum):
    """Service lifetime constants."""

    SINGLETON = "singleton"
    TRANSIENT = "transient"


@dataclass
class ServiceDescriptor:
    """Describes how a service should be created and managed."""

    service_type: type
    implementation: type
    lifetime: ServiceLifetime


def _build_init_kwargs(
    cls: type,
    container: "DependencyContainer",
    overrides: dict[str, Any] | None = None,
    *,
    caller: str = "_build_init_kwargs",
) -> dict[str, Any]:
    """Build keyword arguments for cls.__init__ via dependency resolution.

    Raises:
        DependencyError: If a required parameter cannot be resolved.
    """
    signature = inspect.signature(cls)
    type_hints = get_type_hints(cls.__init__)  # type: ignore[misc]
    init_kwargs: dict[str, Any] = {}
    for param_name, param in signature.parameters.items():
        if param_name == "self" or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if overrides is not None and param_name in overrides:
            init_kwargs[param_name] = overrides[param_name]
            continue
        param_type = type_hints.get(param_name)
        if param_type and container.has(param_type):
            init_kwargs[param_name] = container.get(param_type)
        elif param.default != inspect.Parameter.empty:
            init_kwargs[param_name] = param.default
        else:
            raise DependencyError(
                f"{cls.__name__}: Missing required dependency {param_name}",
                {
                    "param_name": param_name,
                    "class": cls.__name__,
                    "operation": caller,
                },
            )
    return init_kwargs


class DependencyContainer:
    """Lightweight dependency injection container."""

    def __init__(self):
        self._services: dict[type, ServiceDescriptor] = {}
        self._factories: dict[type, Callable] = {}
        self._instances: dict[type, Any] = {}
        self._lock = threading.RLock()

    def register_singleton(
        self, interface: type[T], implementation: type[T]
    ) -> "DependencyContainer":
        """Register a singleton service."""
        self._services[interface] = ServiceDescriptor(
            interface, implementation, ServiceLifetime.SINGLETON
        )
        return self

    def register_transient(
        self, interface: type[T], implementation: type[T]
    ) -> "DependencyContainer":
        """Register a transient service."""
        self._services[interface] = ServiceDescriptor(
            interface, implementation, ServiceLifetime.TRANSIENT
        )
        return self

    def register_factory(
        self, interface: type[T], factory: Callable[[], T]
    ) -> "DependencyContainer":
        """Register a factory function."""
        self._factories[interface] = factory
        return self

    def register_instance(self, interface: type[T], instance: T) -> "DependencyContainer":
        """Register a specific instance."""
        with self._lock:
            self._instances[interface] = instance
        return self

    def get(self, interface: type[T]) -> T:
        """Resolve a dependency."""
        if interface in self._services:
            descriptor = self._services[interface]
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                with self._lock:
                    if interface not in self._instances:
                        instance: Any = self._create_instance(descriptor.implementation)
                        self._instances[interface] = instance
                    return self._instances[interface]  # type: ignore[no-any-return]  # DI container stores Any; caller ensures T via interface key
            return self._create_instance(descriptor.implementation)  # type: ignore[no-any-return]  # descriptor.implementation typed as Type, not Type[T]
        if interface in self._instances:
            return self._instances[interface]  # type: ignore[no-any-return]  # DI container stores Any; caller ensures T via interface key
        if interface in self._factories:
            return self._factories[interface]()  # type: ignore[no-any-return]  # DI factory returns Any; caller ensures T via interface key

        raise DependencyError(
            f"DependencyContainer: Service {interface.__name__} not found",
            {"interface": interface.__name__, "operation": "get_service"},
        )

    def has(self, interface: type) -> bool:
        """Check if a service is registered."""
        return (
            interface in self._services
            or interface in self._factories
            or interface in self._instances
        )

    def _create_instance(self, cls: type[T]) -> T:
        """Create instance with dependency resolution."""
        return cls(**_build_init_kwargs(cls, self, caller="_create_instance"))


class RegistryCategory(StrEnum):
    """Categories of registerable components."""

    PROCESSOR = "processor"
    LOADER = "loader"
    GENERATOR = "generator"
    SERVICE = "service"


class ProcessorRegistry:
    """Registry for managing processor implementations."""

    def __init__(self):
        self._registries: dict[RegistryCategory, dict[str, type]] = {
            category: {} for category in RegistryCategory
        }

    def register(self, category: RegistryCategory, name: str):
        """Decorator to register a component under the given category."""

        def decorator(cls: type):
            registry = self._registries[category]
            if name in registry:
                logger.warning(
                    "Overwriting %s '%s': %s -> %s",
                    category.value,
                    name,
                    registry[name].__name__,
                    cls.__name__,
                )
            registry[name] = cls
            return cls

        return decorator

    def get(self, category: RegistryCategory, name: str) -> type:
        """Get a registered component by category and name."""
        registry = self._registries[category]
        if name not in registry:
            raise ConfigurationError(
                f"{category.value.title()} '{name}' not registered",
                context={f"{category.value}_name": name, "operation": f"get_{category.value}"},
            )
        return registry[name]

    def list_registered(self, category: RegistryCategory) -> dict[str, type]:
        """List all registered components in a category (returns a copy)."""
        return self._registries[category].copy()

    def register_processor(self, name: str):
        """Decorator to register a processor."""
        return self.register(RegistryCategory.PROCESSOR, name)

    def register_loader(self, name: str):
        """Decorator to register a data loader."""
        return self.register(RegistryCategory.LOADER, name)

    def register_generator(self, name: str):
        """Decorator to register a generator."""
        return self.register(RegistryCategory.GENERATOR, name)

    def register_service(self, name: str):
        """Decorator to register a service."""
        return self.register(RegistryCategory.SERVICE, name)

    def get_processor(self, name: str) -> type:
        """Get a processor class by name."""
        return self.get(RegistryCategory.PROCESSOR, name)

    def get_loader(self, name: str) -> type:
        """Get a loader class by name."""
        return self.get(RegistryCategory.LOADER, name)

    def get_generator(self, name: str) -> type:
        """Get a generator class by name."""
        return self.get(RegistryCategory.GENERATOR, name)

    def get_service(self, name: str) -> type:
        """Get a service class by name."""
        return self.get(RegistryCategory.SERVICE, name)

    def list_processors(self) -> dict[str, type]:
        """List all registered processors."""
        return self.list_registered(RegistryCategory.PROCESSOR)

    def list_loaders(self) -> dict[str, type]:
        """List all registered loaders."""
        return self.list_registered(RegistryCategory.LOADER)

    def list_generators(self) -> dict[str, type]:
        """List all registered generators."""
        return self.list_registered(RegistryCategory.GENERATOR)

    def list_services(self) -> dict[str, type]:
        """List all registered services."""
        return self.list_registered(RegistryCategory.SERVICE)


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

    def _create_with_dependencies(self, cls: type, **override_kwargs) -> Any:
        """Create instance with automatic dependency resolution."""
        return cls(
            **_build_init_kwargs(
                cls, self.container, overrides=override_kwargs, caller="_create_with_dependencies"
            )
        )


registry = ProcessorRegistry()

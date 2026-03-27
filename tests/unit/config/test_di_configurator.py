"""Tests for DIConfigurator — DI container wiring and configuration profiles."""

import pytest

from agent_actions.config.di.configurator import ConfigurationProfile, DIConfigurator
from agent_actions.config.di.container import DependencyContainer, ProcessorFactory
from agent_actions.config.di.types import DIConfig
from agent_actions.config.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    ISourceDataLoader,
)
from agent_actions.errors import DependencyError

# ---------------------------------------------------------------------------
# Container creation and configuration
# ---------------------------------------------------------------------------


class TestConfigureContainer:
    """DIConfigurator.configure_container wires all expected services."""

    def test_returns_dependency_container(self):
        config = ConfigurationProfile.development()
        container = DIConfigurator.configure_container(config)
        assert isinstance(container, DependencyContainer)

    def test_core_services_registered(self):
        from agent_actions.config.paths import PathManager

        config = ConfigurationProfile.development()
        container = DIConfigurator.configure_container(config)
        assert container.has(PathManager)

    def test_processor_interfaces_registered(self):
        config = ConfigurationProfile.development()
        container = DIConfigurator.configure_container(config)
        assert container.has(IDataProcessor)
        assert container.has(IGenerator)
        assert container.has(ISourceDataLoader)
        assert container.has(IDataLoader)

    def test_utility_services_registered(self):
        from agent_actions.logging.factory import LoggerFactory
        from agent_actions.prompt.handler import PromptLoader

        config = ConfigurationProfile.development()
        container = DIConfigurator.configure_container(config)
        assert container.has(PromptLoader)
        assert container.has(LoggerFactory)


# ---------------------------------------------------------------------------
# Service registration — different lifetimes
# ---------------------------------------------------------------------------


class TestServiceRegistration:
    """Verify different registration methods on DependencyContainer."""

    def test_register_singleton_returns_same_instance(self):
        container = DependencyContainer()

        class MyService:
            pass

        container.register_singleton(MyService, MyService)
        a = container.get(MyService)
        b = container.get(MyService)
        assert a is b

    def test_register_transient_returns_new_instances(self):
        container = DependencyContainer()

        class MyService:
            pass

        container.register_transient(MyService, MyService)
        a = container.get(MyService)
        b = container.get(MyService)
        assert a is not b

    def test_register_instance_returns_exact_object(self):
        container = DependencyContainer()
        sentinel = object()
        container.register_instance(object, sentinel)
        assert container.get(object) is sentinel

    def test_register_factory(self):
        container = DependencyContainer()
        call_count = 0

        class Svc:
            pass

        def factory():
            nonlocal call_count
            call_count += 1
            return Svc()

        container.register_factory(Svc, factory)
        a = container.get(Svc)
        b = container.get(Svc)
        assert isinstance(a, Svc)
        assert a is not b
        assert call_count == 2


# ---------------------------------------------------------------------------
# Service resolution
# ---------------------------------------------------------------------------


class TestServiceResolution:
    """Verify DI-based resolution (automatic constructor injection)."""

    def test_resolve_with_dependency(self):
        """Transient that depends on a singleton gets it injected."""
        container = DependencyContainer()

        class Dep:
            pass

        class Svc:
            def __init__(self, dep: Dep):
                self.dep = dep

        container.register_singleton(Dep, Dep)
        container.register_transient(Svc, Svc)

        svc = container.get(Svc)
        assert isinstance(svc.dep, Dep)

    def test_resolve_with_default_parameter(self):
        """Parameters with defaults don't need to be registered."""
        container = DependencyContainer()

        class Svc:
            def __init__(self, value: int = 42):
                self.value = value

        container.register_transient(Svc, Svc)
        svc = container.get(Svc)
        assert svc.value == 42

    def test_has_returns_false_for_unregistered(self):
        container = DependencyContainer()

        class Unknown:
            pass

        assert container.has(Unknown) is False


# ---------------------------------------------------------------------------
# Error handling — missing services
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_get_unregistered_service_raises(self):
        container = DependencyContainer()

        class Missing:
            pass

        with pytest.raises(DependencyError):
            container.get(Missing)

    def test_unresolvable_dependency_raises(self):
        """If a constructor requires a type not in the container, raise."""
        container = DependencyContainer()

        class Dep:
            pass

        class Svc:
            def __init__(self, dep: Dep):
                self.dep = dep

        container.register_transient(Svc, Svc)
        with pytest.raises(DependencyError):
            container.get(Svc)


# ---------------------------------------------------------------------------
# ProcessorFactory via DIConfigurator
# ---------------------------------------------------------------------------


class TestProcessorFactory:
    def test_create_processor_factory(self):
        config = ConfigurationProfile.development()
        container = DIConfigurator.configure_container(config)
        factory = DIConfigurator.create_processor_factory(container)
        assert isinstance(factory, ProcessorFactory)


# ---------------------------------------------------------------------------
# configure_for_testing
# ---------------------------------------------------------------------------


class TestConfigureForTesting:
    def test_returns_container(self):
        container = DIConfigurator.configure_for_testing()
        assert isinstance(container, DependencyContainer)

    def test_testing_container_has_interfaces(self):
        container = DIConfigurator.configure_for_testing()
        assert container.has(ISourceDataLoader)
        assert container.has(IDataLoader)
        assert container.has(IDataProcessor)
        assert container.has(IGenerator)

    def test_testing_source_loader_returns_mock_data(self):
        container = DIConfigurator.configure_for_testing()
        loader = container.get(ISourceDataLoader)
        data = loader.load_source_data("any_path")
        assert isinstance(data, list)
        assert len(data) == 2

    def test_testing_processor_returns_empty_list(self):
        container = DIConfigurator.configure_for_testing()
        proc = container.get(IDataProcessor)
        result = proc.process_item({}, [], "guid")
        assert result == []

    def test_testing_generator_returns_tuple(self):
        container = DIConfigurator.configure_for_testing()
        gen = container.get(IGenerator)
        result = gen.create_agent_with_data()
        assert result == ([], True)


# ---------------------------------------------------------------------------
# ConfigurationProfile
# ---------------------------------------------------------------------------


class TestConfigurationProfile:
    @pytest.mark.parametrize(
        "method,expected_env",
        [
            ("development", "development"),
            ("production", "production"),
            ("testing", "testing"),
        ],
    )
    def test_profile_environment(self, method, expected_env):
        profile: DIConfig = getattr(ConfigurationProfile, method)()
        assert profile["environment"] == expected_env

    def test_production_has_parallel_processing(self):
        profile = ConfigurationProfile.production()
        assert profile["processors"]["parallel_processing"] is True

    def test_testing_has_low_batch_size(self):
        profile = ConfigurationProfile.testing()
        assert profile["services"]["batch_size"] == 5

    def test_all_profiles_have_required_keys(self):
        for method in ("development", "production", "testing"):
            profile = getattr(ConfigurationProfile, method)()
            assert "environment" in profile
            assert "logging" in profile
            assert "processors" in profile
            assert "services" in profile

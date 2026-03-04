"""Tests for ProcessorRegistry generic and backward-compat APIs."""

import logging
import logging.handlers

import pytest

from agent_actions.config.di.container import ProcessorRegistry, RegistryCategory
from agent_actions.errors import ConfigurationError


class TestGenericRegistration:
    def test_register_and_get_by_category(self):
        reg = ProcessorRegistry()

        @reg.register(RegistryCategory.PROCESSOR, "test_proc")
        class TestProc:
            pass

        assert reg.get(RegistryCategory.PROCESSOR, "test_proc") is TestProc

    def test_unregistered_name_raises_configuration_error(self):
        reg = ProcessorRegistry()
        with pytest.raises(ConfigurationError, match="not registered"):
            reg.get(RegistryCategory.LOADER, "nonexistent")

    def test_same_name_different_categories_no_collision(self):
        reg = ProcessorRegistry()

        @reg.register(RegistryCategory.PROCESSOR, "shared_name")
        class ProcImpl:
            pass

        @reg.register(RegistryCategory.GENERATOR, "shared_name")
        class GenImpl:
            pass

        assert reg.get(RegistryCategory.PROCESSOR, "shared_name") is ProcImpl
        assert reg.get(RegistryCategory.GENERATOR, "shared_name") is GenImpl

    def test_duplicate_registration_warns(self):
        reg = ProcessorRegistry()

        @reg.register(RegistryCategory.PROCESSOR, "dup")
        class First:
            pass

        # Attach a handler directly to the module logger to capture the warning
        # (avoids caplog fragility when other tests reconfigure logging).
        target_logger = logging.getLogger("agent_actions.config.di.container")
        handler = logging.handlers.MemoryHandler(capacity=10)
        handler.setLevel(logging.WARNING)
        target_logger.addHandler(handler)
        try:

            @reg.register(RegistryCategory.PROCESSOR, "dup")
            class Second:
                pass

        finally:
            target_logger.removeHandler(handler)

        assert reg.get(RegistryCategory.PROCESSOR, "dup") is Second
        messages = [handler.format(r) for r in handler.buffer]
        assert any("Overwriting processor 'dup'" in m for m in messages)

    def test_list_registered_returns_copy(self):
        reg = ProcessorRegistry()

        @reg.register(RegistryCategory.SERVICE, "svc")
        class SvcImpl:
            pass

        listing = reg.list_registered(RegistryCategory.SERVICE)
        assert listing == {"svc": SvcImpl}

        # Mutating the copy doesn't affect the registry
        listing["injected"] = object
        assert "injected" not in reg.list_registered(RegistryCategory.SERVICE)


class TestBackwardCompatDecorators:
    def test_register_processor_decorator(self):
        reg = ProcessorRegistry()

        @reg.register_processor("my_proc")
        class MyProc:
            pass

        assert reg.get_processor("my_proc") is MyProc

    def test_register_loader_decorator(self):
        reg = ProcessorRegistry()

        @reg.register_loader("my_loader")
        class MyLoader:
            pass

        assert reg.get_loader("my_loader") is MyLoader

    def test_register_generator_decorator(self):
        reg = ProcessorRegistry()

        @reg.register_generator("my_gen")
        class MyGen:
            pass

        assert reg.get_generator("my_gen") is MyGen

    def test_register_service_decorator(self):
        reg = ProcessorRegistry()

        @reg.register_service("my_svc")
        class MySvc:
            pass

        assert reg.get_service("my_svc") is MySvc

    def test_list_processors(self):
        reg = ProcessorRegistry()

        @reg.register_processor("p1")
        class P1:
            pass

        @reg.register_processor("p2")
        class P2:
            pass

        result = reg.list_processors()
        assert result == {"p1": P1, "p2": P2}

    def test_list_loaders(self):
        reg = ProcessorRegistry()

        @reg.register_loader("l1")
        class L1:
            pass

        assert reg.list_loaders() == {"l1": L1}

    def test_list_generators(self):
        reg = ProcessorRegistry()

        @reg.register_generator("g1")
        class G1:
            pass

        assert reg.list_generators() == {"g1": G1}

    def test_list_services(self):
        reg = ProcessorRegistry()

        @reg.register_service("s1")
        class S1:
            pass

        assert reg.list_services() == {"s1": S1}

    def test_get_unregistered_processor_raises(self):
        reg = ProcessorRegistry()
        with pytest.raises(ConfigurationError, match="Processor"):
            reg.get_processor("missing")

    def test_get_unregistered_loader_raises(self):
        reg = ProcessorRegistry()
        with pytest.raises(ConfigurationError, match="Loader"):
            reg.get_loader("missing")

    def test_get_unregistered_generator_raises(self):
        reg = ProcessorRegistry()
        with pytest.raises(ConfigurationError, match="Generator"):
            reg.get_generator("missing")

    def test_get_unregistered_service_raises(self):
        reg = ProcessorRegistry()
        with pytest.raises(ConfigurationError, match="Service"):
            reg.get_service("missing")

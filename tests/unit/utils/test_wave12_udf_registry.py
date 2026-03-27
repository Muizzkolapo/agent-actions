"""Wave 12 T2-5 regression: clear_registry() removes UDF modules from sys.modules."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from agent_actions.utils.udf_management.registry import (
    UDF_REGISTRY,
    _registered_modules,
    clear_registry,
    udf_tool,
)


class TestUDFRegistrySysModulesSync:
    """T2-5: clear_registry() must evict UDF module names from sys.modules."""

    def setup_method(self):
        """Ensure registry is clean before each test."""
        clear_registry()

    def teardown_method(self):
        """Clean up after each test."""
        clear_registry()

    def test_clear_registry_removes_udf_module_from_sys_modules(self):
        """After clear_registry(), the module that registered a UDF must be evicted."""
        module_name = "_test_udf_wave12_module"

        # Create a fake module and inject it into sys.modules
        fake_mod = types.ModuleType(module_name)
        sys.modules[module_name] = fake_mod

        # Register a UDF as if it came from that module
        def my_udf(x):
            """Test UDF."""
            return x

        my_udf.__module__ = module_name
        udf_tool(my_udf)

        assert module_name in _registered_modules
        assert module_name in sys.modules

        clear_registry()

        assert module_name not in sys.modules
        assert module_name not in _registered_modules
        assert len(UDF_REGISTRY) == 0

    def test_clear_registry_tolerates_missing_sys_module(self):
        """clear_registry() must not raise if a tracked module is not in sys.modules."""
        module_name = "_test_udf_not_in_sys_modules"

        def my_udf2(x):
            """Test UDF 2."""
            return x

        my_udf2.__module__ = module_name
        udf_tool(my_udf2)

        # Do NOT inject into sys.modules
        assert module_name not in sys.modules

        # Should not raise
        clear_registry()
        assert len(UDF_REGISTRY) == 0

    def test_reimport_after_clear_re_registers(self):
        """After clear_registry() evicts a module, a fresh import re-registers the UDF."""
        module_name = "_test_reimport_wave12"
        fake_mod = types.ModuleType(module_name)
        sys.modules[module_name] = fake_mod

        def my_udf3(x):
            return x

        my_udf3.__module__ = module_name
        udf_tool(my_udf3)
        assert "my_udf3" in UDF_REGISTRY

        clear_registry()
        assert "my_udf3" not in UDF_REGISTRY
        assert module_name not in sys.modules

        # Re-register (simulates re-import)
        fake_mod2 = types.ModuleType(module_name)
        sys.modules[module_name] = fake_mod2
        udf_tool(my_udf3)
        assert "my_udf3" in UDF_REGISTRY

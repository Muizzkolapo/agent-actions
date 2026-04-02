"""Vendor parity tests — ensures each client class declares CAPABILITIES."""

import copy
import importlib
from unittest.mock import patch

import pytest

from agent_actions.llm.realtime.services.invocation import _VENDOR_PACKAGES, CLIENT_REGISTRY
from agent_actions.validation.preflight.vendor_compatibility_validator import (
    VALID_VENDORS,
    VendorCompatibilityValidator,
    _get_vendor_capabilities,
    _resolve_capabilities,
)

# Snapshot the original registry so tests can restore lazy-string entries
# after earlier tests resolve them into class objects.
_ORIGINAL_REGISTRY = copy.copy(CLIENT_REGISTRY)


@pytest.fixture(autouse=True)
def reset_vendor_cache():
    VendorCompatibilityValidator.clear_cache()
    yield
    # Restore lazy-string entries that may have been resolved during the test.
    CLIENT_REGISTRY.update(_ORIGINAL_REGISTRY)
    VendorCompatibilityValidator.clear_cache()


EXPECTED_CAPABILITY_KEYS = {
    "supports_json_mode",
    "supports_batch",
    "supports_tools",
    "supports_vision",
    "required_fields",
    "optional_fields",
}


def _resolve_class(entry):
    """Resolve a CLIENT_REGISTRY entry to its class."""
    if isinstance(entry, str):
        module_path, class_name = entry.split(":", 1)
        return getattr(importlib.import_module(module_path), class_name)
    return entry


class TestVendorParity:
    """Ensure every client in CLIENT_REGISTRY declares CAPABILITIES."""

    def test_valid_vendors_derived_from_client_registry(self):
        """VALID_VENDORS must equal CLIENT_REGISTRY keys (single source of truth)."""
        assert VALID_VENDORS == set(CLIENT_REGISTRY.keys())

    def test_every_client_has_capabilities(self):
        """Each client class in CLIENT_REGISTRY must have a non-empty CAPABILITIES dict."""
        for vendor, entry in CLIENT_REGISTRY.items():
            cls = _resolve_class(entry)
            assert hasattr(cls, "CAPABILITIES"), (
                f"Client class for '{vendor}' ({cls.__name__}) is missing CAPABILITIES"
            )
            assert cls.CAPABILITIES, (
                f"Client class for '{vendor}' ({cls.__name__}) has empty CAPABILITIES"
            )

    def test_capabilities_have_expected_keys(self):
        """Each CAPABILITIES dict must contain the standard set of keys."""
        for vendor, entry in CLIENT_REGISTRY.items():
            cls = _resolve_class(entry)
            caps = cls.CAPABILITIES
            missing = EXPECTED_CAPABILITY_KEYS - set(caps.keys())
            assert not missing, f"CAPABILITIES for '{vendor}' is missing keys: {missing}"

    def test_vendor_capabilities_map_matches_client_classes(self):
        """Module-level VENDOR_CAPABILITIES must match each client's CAPABILITIES."""
        for vendor, entry in CLIENT_REGISTRY.items():
            cls = _resolve_class(entry)
            caps = _get_vendor_capabilities()
            assert caps[vendor] is cls.CAPABILITIES, (
                f"VENDOR_CAPABILITIES['{vendor}'] does not reference {cls.__name__}.CAPABILITIES"
            )

    def test_resolve_capabilities_returns_dict_for_all_vendors(self):
        """_resolve_capabilities must return a dict for every registered vendor."""
        for vendor in CLIENT_REGISTRY:
            caps = _resolve_capabilities(vendor)
            assert isinstance(caps, dict), (
                f"_resolve_capabilities('{vendor}') returned {type(caps)}"
            )

    def test_all_runtime_vendors_pass_validation(self):
        """Each runtime vendor should pass preflight validation with minimal config."""
        validator = VendorCompatibilityValidator()
        for vendor in CLIENT_REGISTRY:
            caps = _resolve_capabilities(vendor)
            assert caps is not None
            config: dict = {"model_vendor": vendor}
            for field in caps.get("required_fields", []):
                config[field] = "test-value"
            result = validator.validate_vendor_config(config)
            assert result, f"Vendor '{vendor}' failed preflight: {validator.get_errors()}"

    def test_vendor_packages_covers_all_lazy_entries(self):
        """Every lazy-string entry in CLIENT_REGISTRY must have a _VENDOR_PACKAGES mapping."""
        lazy_vendors = {k for k, v in CLIENT_REGISTRY.items() if isinstance(v, str)}
        missing = lazy_vendors - set(_VENDOR_PACKAGES)
        assert not missing, (
            f"Lazy vendors missing from _VENDOR_PACKAGES: {missing}. "
            "Add entries so DependencyError shows the correct pip package name."
        )

    def test_clear_cache_reinitialises_on_next_access(self):
        """clear_cache() resets the cache so the next call to _get_vendor_capabilities re-builds it."""
        caps_first = _get_vendor_capabilities()
        VendorCompatibilityValidator.clear_cache()
        caps_second = _get_vendor_capabilities()
        assert caps_first == caps_second

    def test_resolve_client_raises_dependency_error_on_missing_sdk(self):
        """_resolve_client must raise DependencyError with correct context when SDK is missing."""
        from agent_actions.errors import DependencyError
        from agent_actions.llm.realtime.services.invocation import _resolve_client

        # Force a lazy string entry so the import path is exercised.
        CLIENT_REGISTRY["mistral"] = _ORIGINAL_REGISTRY["mistral"]

        with patch.object(importlib, "import_module", side_effect=ImportError("no module")):
            with pytest.raises(DependencyError) as exc_info:
                _resolve_client("mistral")

        err = exc_info.value
        assert "mistralai" in str(err)
        assert err.context["package"] == "mistralai"
        assert err.context["install_command"] == "uv pip install mistralai"
        assert err.context["client_type"] == "mistral"

    def test_resolve_capabilities_returns_none_on_missing_sdk(self):
        """_resolve_capabilities must return None (not crash) when SDK is missing."""
        # Force a lazy string entry.
        CLIENT_REGISTRY["mistral"] = _ORIGINAL_REGISTRY["mistral"]

        with patch.object(importlib, "import_module", side_effect=ImportError("no module")):
            result = _resolve_capabilities("mistral")

        assert result is None

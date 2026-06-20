"""Regression: _resolve_client replaces lazy import strings with resolved classes.

The CLIENT_REGISTRY holds lazy "module:Class" strings for external SDK providers
so the CLI does not crash if a provider's SDK is missing. _resolve_client must
import the module on first use and return the resolved class.

Bug regression: PR #632 changed the cache update from `CLIENT_REGISTRY[v] = cls`
to `CLIENT_REGISTRY.setdefault(v, cls)` for "thread safety", but setdefault is a
no-op when the key already exists — so the lazy string was never replaced, and
the next `return CLIENT_REGISTRY[v]` handed back the lazy string. Downstream
code then called .invoke() on a str, producing
"'str' object has no attribute 'invoke'" at the first LLM call.
"""

import copy

import pytest

from agent_actions.llm.realtime.services.invocation import (
    CLIENT_REGISTRY,
    _resolve_client,
)

_ORIGINAL_REGISTRY = copy.copy(CLIENT_REGISTRY)


@pytest.fixture(autouse=True)
def restore_registry():
    yield
    CLIENT_REGISTRY.clear()
    CLIENT_REGISTRY.update(_ORIGINAL_REGISTRY)


class TestResolveClientLazyImport:
    """_resolve_client must return a class, never the lazy import string."""

    @pytest.mark.parametrize(
        "vendor",
        ["openai", "ollama_local", "ollama_cloud", "anthropic", "gemini", "cohere", "groq"],
    )
    def test_lazy_vendor_resolves_to_class_not_string(self, vendor):
        """Each lazy-loaded provider resolves to an importable class with .invoke."""
        # Force lazy state: restore the string entry before resolving.
        CLIENT_REGISTRY[vendor] = _ORIGINAL_REGISTRY[vendor]
        assert isinstance(CLIENT_REGISTRY[vendor], str), "precondition: starts as lazy string"

        resolved = _resolve_client(vendor)

        assert not isinstance(resolved, str), (
            f"_resolve_client returned the lazy string for {vendor!r} — "
            "calling .invoke() on a str would fail at runtime"
        )
        assert hasattr(resolved, "invoke"), f"resolved client for {vendor!r} must expose .invoke()"

    def test_resolve_caches_class_in_registry(self):
        """After resolution, the registry entry is the class (subsequent calls skip the import)."""
        CLIENT_REGISTRY["openai"] = _ORIGINAL_REGISTRY["openai"]
        _resolve_client("openai")
        assert not isinstance(CLIENT_REGISTRY["openai"], str), (
            "registry should hold the resolved class after first call"
        )

    def test_eager_internal_clients_returned_directly(self):
        """tool/agac-provider/hitl are pre-loaded classes, returned as-is."""
        for vendor in ("tool", "agac-provider", "hitl"):
            entry = CLIENT_REGISTRY[vendor]
            assert not isinstance(entry, str), f"{vendor} should be an eagerly loaded class"
            assert _resolve_client(vendor) is entry

"""Shared fixtures for expectation-engine tests."""

import pytest

from agent_actions.expectations import registry as registry_module


@pytest.fixture
def preserve_registry():
    """Snapshot and restore the process-global type registry around a test."""
    saved_registry = dict(registry_module._REGISTRY)
    saved_sources = dict(registry_module._USER_CHECK_SOURCES)
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(saved_registry)
    registry_module._USER_CHECK_SOURCES.clear()
    registry_module._USER_CHECK_SOURCES.update(saved_sources)

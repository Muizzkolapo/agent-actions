"""
Shared fixtures for integration tests.

This module provides fixtures used across integration tests, including
batch vs online parity testing.
"""

from typing import Any

import pytest

# =============================================================================
# Parity Test Fixtures
# =============================================================================


@pytest.fixture
def parity_agent_config() -> dict[str, Any]:
    """
    Agent configuration for batch vs online parity testing.

    Includes context_scope with observe/drop/passthrough to exercise
    all context transformation paths.
    """
    return {
        "name": "parity_test_agent",
        "agent_type": "llm_agent",
        "model_vendor": "mock",
        "model_name": "mock-model",
        "json_mode": True,
        "prompt": "Process the following: {{ source.text }}",
        "context_scope": {
            "observe": ["source.text", "source.metadata"],
            "drop": ["source.internal_id"],
            "passthrough": ["source.record_id"],
        },
    }


@pytest.fixture
def parity_agent_config_no_context_scope() -> dict[str, Any]:
    """
    Agent configuration with minimal context_scope for baseline parity testing.

    context_scope is required — this uses a minimal observe to access source.text
    which the prompt template references.
    """
    return {
        "name": "parity_test_agent_simple",
        "agent_type": "llm_agent",
        "model_vendor": "mock",
        "model_name": "mock-model",
        "json_mode": True,
        "prompt": "Process: {{ source.text }}",
        "context_scope": {
            "observe": ["source.text"],
        },
    }


@pytest.fixture
def parity_contents() -> dict[str, Any]:
    """
    Sample contents for parity testing.

    Includes various field types to test context building.
    """
    return {
        "text": "Sample text for processing",
        "metadata": {"source": "test", "priority": "high"},
        "internal_id": "secret-123",
        "record_id": "rec-001",
    }


@pytest.fixture
def parity_current_item() -> dict[str, Any]:
    """
    Current item context for parity testing.

    Mimics a typical batch/online item with source_guid and lineage.
    """
    return {
        "source_guid": "test-guid-001",
        "node_id": "node_1_parity_test_agent",
        "lineage": ["node_0_source"],
        "content": {
            "text": "Sample text for processing",
            "metadata": {"source": "test", "priority": "high"},
            "internal_id": "secret-123",
            "record_id": "rec-001",
        },
    }


@pytest.fixture
def parity_agent_indices() -> dict[str, int]:
    """Agent indices mapping for parity testing."""
    return {
        "source": 0,
        "parity_test_agent": 1,
        "parity_test_agent_simple": 1,
    }


@pytest.fixture
def parity_dependency_configs() -> dict[str, dict[str, Any]]:
    """Dependency configurations for parity testing."""
    return {
        "source": {
            "idx": 0,
            "output": ["text", "metadata", "internal_id", "record_id"],
        }
    }

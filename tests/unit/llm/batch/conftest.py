"""Shared fixtures for the batch tests."""

import pytest

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator


@pytest.fixture
def batch_preparator() -> BatchTaskPreparator:
    """BatchTaskPreparator wired with default empty config."""
    return BatchTaskPreparator(
        action_indices={},
        dependency_configs={},
        storage_backend=None,
        version_context=None,
    )

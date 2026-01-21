"""Shared test fixtures for batch module tests.

This module provides common fixtures used across batch module tests,
enabling consistent test data and mock objects for TDD.
"""

import pytest
from pathlib import Path
from typing import Dict, List, Any
from unittest.mock import MagicMock


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_batch_data() -> List[Dict[str, Any]]:
    """Generate sample batch input data for testing.

    Returns:
        List of sample records with typical batch input fields.
    """
    return [
        {
            "id": "record-1",
            "source_guid": "guid-001",
            "content": {"text": "First test content", "metadata": {"source": "test"}},
        },
        {
            "id": "record-2",
            "source_guid": "guid-002",
            "content": {"text": "Second test content", "metadata": {"source": "test"}},
        },
        {
            "id": "record-3",
            "source_guid": "guid-003",
            "content": {"text": "Third test content", "metadata": {"source": "test"}},
        },
    ]


@pytest.fixture
def sample_context_map() -> Dict[str, Dict[str, Any]]:
    """Generate sample context map with filter statuses.

    Returns:
        Context map keyed by target_id with various filter statuses.
    """
    return {
        "task-001": {
            "source_guid": "guid-001",
            "content": {"text": "Included content"},
            "_batch_filter_status": "included",
        },
        "task-002": {
            "source_guid": "guid-002",
            "content": {"text": "Skipped content"},
            "_batch_filter_status": "skipped",
        },
        "task-003": {
            "source_guid": "guid-003",
            "content": {"text": "Filtered content"},
            "_batch_filter_status": "filtered",
        },
        "task-004": {
            "source_guid": "guid-004",
            "content": {"text": "Another included"},
            "_batch_filter_status": "included",
            "_passthrough_fields": {"original_id": "123"},
        },
    }


@pytest.fixture
def sample_batch_results() -> List[Dict[str, Any]]:
    """Generate sample batch results from provider.

    Returns:
        List of batch result objects simulating provider responses.
    """
    return [
        {
            "custom_id": "task-001",
            "response": {
                "status_code": 200,
                "body": {"choices": [{"message": {"content": '{"result": "success"}'}}]},
            },
        },
        {
            "custom_id": "task-004",
            "response": {
                "status_code": 200,
                "body": {"choices": [{"message": {"content": '{"result": "processed"}'}}]},
            },
        },
    ]


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def minimal_agent_config() -> Dict[str, Any]:
    """Minimal valid agent configuration for testing.

    Returns:
        Agent config dict with required fields only.
    """
    return {
        "name": "test_agent",
        "agent_type": "test_agent",
        "model_vendor": "mock",
        "model_name": "mock-model",
        "json_mode": True,
    }


@pytest.fixture
def full_agent_config(minimal_agent_config) -> Dict[str, Any]:
    """Complete agent configuration with all optional fields.

    Returns:
        Agent config dict with all common fields populated.
    """
    return {
        **minimal_agent_config,
        "workflow_config_path": "/tmp/test/agent_config/test.yml",
        "context_scope": {
            "drop": ["source.api_key"],
            "observe": ["previous_action.output"],
        },
        "schema_name": "test_schema",
        "retry": {"enabled": True, "max_attempts": 3},
    }


# =============================================================================
# Registry Fixtures
# =============================================================================


@pytest.fixture
def mock_registry_manager(tmp_path):
    """Create a BatchRegistryManager with temporary file.

    Args:
        tmp_path: Pytest fixture providing temp directory.

    Returns:
        BatchRegistryManager instance for testing.
    """
    from agent_actions.llm.batch.infrastructure.registry import (
        BatchRegistryManager,
    )

    registry_path = tmp_path / "batch" / ".batch_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    return BatchRegistryManager(registry_path)


@pytest.fixture
def populated_registry(mock_registry_manager):
    """Registry pre-populated with sample batch jobs.

    Returns:
        Tuple of (registry_manager, dict of batch_ids by status).
    """
    from agent_actions.llm.batch.core.batch_models import BatchJobEntry
    from datetime import datetime

    batch_ids = {}

    # Completed batch
    completed_entry = BatchJobEntry(
        batch_id="batch_completed_001",
        status="completed",
        timestamp=datetime.now().isoformat(),
        provider="mock",
        record_count=10,
    )
    mock_registry_manager.save_batch_job(completed_entry, "completed_file.json")
    batch_ids["completed"] = completed_entry.batch_id

    # In-progress batch
    in_progress_entry = BatchJobEntry(
        batch_id="batch_inprogress_002",
        status="in_progress",
        timestamp=datetime.now().isoformat(),
        provider="mock",
        record_count=5,
    )
    mock_registry_manager.save_batch_job(in_progress_entry, "inprogress_file.json")
    batch_ids["in_progress"] = in_progress_entry.batch_id

    # Failed batch
    failed_entry = BatchJobEntry(
        batch_id="batch_failed_003",
        status="failed",
        timestamp=datetime.now().isoformat(),
        provider="mock",
        record_count=3,
    )
    mock_registry_manager.save_batch_job(failed_entry, "failed_file.json")
    batch_ids["failed"] = failed_entry.batch_id

    return mock_registry_manager, batch_ids


# =============================================================================
# Mock Client Fixtures
# =============================================================================


@pytest.fixture
def mock_batch_client():
    """Create a mock batch client for testing.

    Returns:
        MagicMock configured as a batch client.
    """
    client = MagicMock()
    client.submit_batch.return_value = "mock_batch_id_12345"
    client.get_batch_status.return_value = "completed"
    client.get_batch_results.return_value = []
    return client


@pytest.fixture
def mock_client_resolver(mock_batch_client):
    """Create a mock client resolver.

    Returns:
        MagicMock that returns mock_batch_client for any config.
    """
    resolver = MagicMock()
    resolver.get_for_config.return_value = mock_batch_client
    return resolver


# =============================================================================
# Path Fixtures
# =============================================================================


@pytest.fixture
def batch_output_dir(tmp_path) -> Path:
    """Create a temporary batch output directory structure.

    Returns:
        Path to the output directory with proper structure.
    """
    output_dir = tmp_path / "agent_io" / "node_1_test_agent"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create batch subdirectory
    batch_dir = output_dir / "batch"
    batch_dir.mkdir(exist_ok=True)

    return output_dir

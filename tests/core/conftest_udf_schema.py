"""
Pytest configuration for UDF schema tests.

Provides shared fixtures and test utilities.
"""

import pytest

from agent_actions.utils.udf_management.registry import clear_registry


@pytest.fixture(autouse=True)
def reset_udf_registry():
    """
    Automatically clear UDF registry before and after each test.

    This ensures test isolation and prevents test interference.
    """
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def sample_inline_schema():
    """Provide a sample inline schema for testing."""
    return {
        "name": "sample_schema",
        "description": "Sample schema for testing",
        "fields": [
            {"id": "text", "type": "string", "required": True},
            {"id": "count", "type": "number", "required": False},
        ],
    }


@pytest.fixture
def sample_simple_schema():
    """Provide a simple dict schema for testing."""
    return {
        "text": "string!",  # Required
        "count": "number",  # Optional
        "tags": "array",
    }


@pytest.fixture
def sample_file_schema_content():
    """Provide sample YAML schema file content."""
    return """
name: file_based_schema
description: Schema loaded from file

fields:
  - id: user_id
    type: string
    description: User identifier
    required: true

  - id: email
    type: string
    description: User email
    required: true
    pattern: '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'

  - id: age
    type: number
    description: User age
    required: false

  - id: tags
    type: array
    description: User tags
    required: false
    items:
      type: string
"""


@pytest.fixture
def sample_batch_schema():
    """Provide a sample schema for FILE mode (batch processing)."""
    return {
        "name": "batch_schema",
        "description": "Schema for batch processing",
        "fields": [
            {
                "id": "items",
                "type": "array",
                "required": True,
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "value": {"type": "number"}},
                    "required": ["id", "value"],
                },
            }
        ],
    }

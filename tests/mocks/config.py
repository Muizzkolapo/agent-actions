"""Mock configurations for testing."""

from typing import Dict, Any, List, Optional
from unittest.mock import Mock

# Mock configuration data
mock_agent_config = {
    "agent_type": "test_agent",
    "environment": "testing",
    "run_mode": "sync",
    "logging": {
        "level": "ERROR",
        "format": "%(levelname)s - %(message)s"
    },
    "processors": {
        "cache_enabled": False,
        "parallel_processing": False,
        "timeout": 30
    },
    "vendors": {
        "openai": {
            "api_key": "test-key-123",
            "model": "gpt-3.5-turbo"
        },
        "anthropic": {
            "api_key": "test-key-456",
            "model": "claude-3-sonnet"
        }
    }
}

mock_path_config = {
    "project_root": "/tmp/test_project",
    "source_dir": "source",
    "staging_dir": "staging",
    "target_dir": "target",
    "artifacts_dir": "artifacts"
}

mock_processor_config = {
    "batch_size": 10,
    "max_retries": 3,
    "retry_delay": 1.0,
    "timeout": 30
}


def create_mock_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a mock configuration with optional overrides."""
    config = {
        **mock_agent_config,
        "paths": mock_path_config,
        "processing": mock_processor_config
    }

    if overrides:
        config.update(overrides)

    return config


def create_mock_vendor():
    """Create a mock vendor for testing."""
    mock_vendor = Mock()
    mock_vendor.generate_content.return_value = {
        "content": "Test response",
        "usage": {"total_tokens": 100}
    }
    mock_vendor.is_available.return_value = True
    return mock_vendor


def create_mock_data_loader():
    """Create a mock data loader for testing."""
    mock_loader = Mock()
    mock_loader.load.return_value = [
        {"id": 1, "content": "Test data 1"},
        {"id": 2, "content": "Test data 2"}
    ]
    mock_loader.validate.return_value = True
    return mock_loader


def create_mock_processor():
    """Create a mock processor for testing."""
    mock_processor = Mock()
    mock_processor.process.return_value = {
        "processed_data": "Test processed content",
        "metadata": {"processing_time": 0.1}
    }
    mock_processor.is_enabled.return_value = True
    return mock_processor
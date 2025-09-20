import os
import sys
import tempfile
import shutil
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch, MagicMock

import pytest
import click
from click.testing import CliRunner


def pytest_configure():
    # Ensure project root is on sys.path for imports during tests.
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


# ============================================================================
# Project Structure and Path Fixtures
# ============================================================================

@pytest.fixture
def project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory for testing."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """Create a temporary output directory for testing."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary config directory for testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


# ============================================================================
# CLI Testing Fixtures
# ============================================================================

@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Click CliRunner for testing CLI commands."""
    return CliRunner()


@pytest.fixture
def isolated_cli_runner() -> CliRunner:
    """Provide an isolated Click CliRunner that doesn't affect real filesystem."""
    return CliRunner(env={'AGENT_ACTIONS_TEST_MODE': 'true'})


@pytest.fixture
def mock_cli_args() -> List[str]:
    """Provide mock CLI arguments for testing."""
    return ['--debug', 'test', '--output', '/tmp/test']


# ============================================================================
# Configuration and Data Fixtures
# ============================================================================

@pytest.fixture
def sample_config() -> Dict[str, Any]:
    """Provide a sample configuration for testing."""
    return {
        "name": "test_project",
        "version": "1.0.0",
        "agents": [
            {
                "name": "test_agent",
                "type": "generator",
                "config": {
                    "source": "test_source",
                    "target": "test_target"
                }
            }
        ],
        "workflows": [
            {
                "name": "test_workflow",
                "steps": ["extract", "transform", "generate"]
            }
        ]
    }


@pytest.fixture
def sample_config_file(tmp_path: Path, sample_config: Dict[str, Any]) -> Path:
    """Create a sample configuration file for testing."""
    config_file = tmp_path / "config.json"
    with open(config_file, 'w') as f:
        json.dump(sample_config, f, indent=2)
    return config_file


@pytest.fixture
def invalid_config() -> Dict[str, Any]:
    """Provide an invalid configuration for error testing."""
    return {
        "name": "",  # Invalid empty name
        "version": "not-a-semver",  # Invalid version
        "agents": [
            {
                "name": "invalid_agent",
                "type": "unknown_type",  # Invalid type
                "config": {}  # Missing required config
            }
        ]
    }


@pytest.fixture
def sample_where_clauses() -> List[str]:
    """Provide sample WHERE clauses for parser testing."""
    return [
        "field = 'value'",
        "age > 18 AND status = 'active'",
        "category IN ('A', 'B', 'C')",
        "name LIKE '%test%'",
        "nested.field != null",
        "count >= 10 OR priority = 'high'"
    ]


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_json_data() -> List[Dict[str, Any]]:
    """Provide sample JSON data for testing loaders."""
    return [
        {"id": 1, "name": "Alice", "age": 30, "department": "Engineering"},
        {"id": 2, "name": "Bob", "age": 25, "department": "Marketing"},
        {"id": 3, "name": "Charlie", "age": 35, "department": "Sales"}
    ]


@pytest.fixture
def sample_csv_data() -> str:
    """Provide sample CSV data for testing tabular loaders."""
    return """id,name,age,department
1,Alice,30,Engineering
2,Bob,25,Marketing
3,Charlie,35,Sales"""


@pytest.fixture
def sample_xml_data() -> str:
    """Provide sample XML data for testing XML loaders."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<employees>
    <employee id="1">
        <name>Alice</name>
        <age>30</age>
        <department>Engineering</department>
    </employee>
    <employee id="2">
        <name>Bob</name>
        <age>25</age>
        <department>Marketing</department>
    </employee>
</employees>"""


@pytest.fixture
def sample_text_data() -> str:
    """Provide sample text data for testing text loaders."""
    return """This is a sample text file.
It contains multiple lines.
Each line represents different content.
This can be used for testing text processing."""


# ============================================================================
# Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing."""
    return Mock()


@pytest.fixture
def mock_file_system(tmp_path: Path):
    """Provide a mock file system for testing file operations."""
    mock_fs = Mock()
    mock_fs.root = tmp_path
    mock_fs.exists = Mock(return_value=True)
    mock_fs.read = Mock(return_value="test content")
    mock_fs.write = Mock()
    mock_fs.mkdir = Mock()
    return mock_fs


@pytest.fixture
def mock_agent():
    """Provide a mock agent for testing."""
    agent = Mock()
    agent.name = "test_agent"
    agent.type = "generator"
    agent.process = Mock(return_value={"status": "success", "data": []})
    agent.validate = Mock(return_value=True)
    return agent


@pytest.fixture
def mock_workflow():
    """Provide a mock workflow for testing."""
    workflow = Mock()
    workflow.name = "test_workflow"
    workflow.steps = ["extract", "transform", "generate"]
    workflow.execute = Mock(return_value={"status": "completed", "results": []})
    return workflow


@pytest.fixture
def mock_external_api():
    """Provide a mock external API for testing integrations."""
    api = Mock()
    api.get = Mock(return_value={"status": 200, "data": {"result": "success"}})
    api.post = Mock(return_value={"status": 201, "data": {"id": "123"}})
    api.put = Mock(return_value={"status": 200, "data": {"updated": True}})
    api.delete = Mock(return_value={"status": 204})
    return api


# ============================================================================
# Environment and Settings Fixtures
# ============================================================================

@pytest.fixture
def test_environment_vars() -> Dict[str, str]:
    """Provide test environment variables."""
    return {
        "AGENT_ACTIONS_TEST_MODE": "true",
        "AGENT_ACTIONS_LOG_LEVEL": "DEBUG",
        "AGENT_ACTIONS_CONFIG_DIR": "/tmp/test_config",
        "AGENT_ACTIONS_OUTPUT_DIR": "/tmp/test_output"
    }


@pytest.fixture
def mock_env_vars(test_environment_vars: Dict[str, str]):
    """Mock environment variables for testing."""
    with patch.dict(os.environ, test_environment_vars):
        yield test_environment_vars


# ============================================================================
# Error Simulation Fixtures
# ============================================================================

@pytest.fixture
def mock_permission_error():
    """Provide a mock permission error for testing error handling."""
    return PermissionError("Permission denied: /protected/file")


@pytest.fixture
def mock_file_not_found_error():
    """Provide a mock file not found error for testing error handling."""
    return FileNotFoundError("No such file or directory: /missing/file")


@pytest.fixture
def mock_network_error():
    """Provide a mock network error for testing error handling."""
    return ConnectionError("Failed to connect to remote service")


# ============================================================================
# Parametrized Test Data
# ============================================================================

@pytest.fixture(params=[
    ("test_project", True),
    ("", False),
    ("project-with-dashes", True),
    ("project_with_underscores", True),
    ("123numeric-start", False),
    ("project with spaces", False),
    ("very-long-project-name-that-exceeds-reasonable-limits-and-should-be-rejected", False)
])
def project_name_data(request):
    """Parametrized project names for validation testing."""
    return request.param


@pytest.fixture(params=[
    ({"field": "value"}, "field = 'value'", True),
    ({"age": 25}, "age > 18", True),
    ({"status": "inactive"}, "status = 'active'", False),
    ({}, "field = 'value'", False),
    ({"field": None}, "field != null", False)
])
def where_clause_data(request):
    """Parametrized data for WHERE clause testing."""
    return request.param


# ============================================================================
# Cleanup Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def cleanup_temp_files():
    """Automatically cleanup temporary files after each test."""
    yield
    # Cleanup logic runs after each test
    temp_dirs = ["/tmp/agent_actions_test", "/tmp/test_output", "/tmp/test_config"]
    for temp_dir in temp_dirs:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


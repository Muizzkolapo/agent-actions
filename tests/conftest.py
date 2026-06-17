import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from click.testing import CliRunner


def pytest_configure():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Click CliRunner for testing CLI commands."""
    return CliRunner()


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """Create a temporary output directory for testing."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing."""
    return Mock()


@pytest.fixture
def sample_batch_task():
    """Standard BatchTask for testing all batch providers."""
    from agent_actions.llm.providers.batch_base import BatchTask

    return BatchTask(
        custom_id="test-123",
        prompt="You are a helpful assistant",
        user_content='{"question": "What is 2+2?"}',
        model_config={"model_name": "test-model", "temperature": 0.7, "max_tokens": 100},
    )


@pytest.fixture
def sample_batch_task_no_max_tokens():
    """BatchTask without max_tokens (for Bug #2 validation)."""
    from agent_actions.llm.providers.batch_base import BatchTask

    return BatchTask(
        custom_id="test-456",
        prompt="You are helpful",
        user_content='{"test": "data"}',
        model_config={"model_name": "test-model", "temperature": 0.5},
    )


@pytest.fixture
def sample_data() -> list[dict[str, Any]]:
    """Sample data list for testing prepare_tasks() method."""
    return [
        {"target_id": "1", "content": {"question": "Question 1"}},
        {"target_id": "2", "content": {"question": "Question 2"}},
        {"target_id": "3", "content": {"question": "Question 3"}},
    ]


@pytest.fixture
def sample_agent_config_json_mode() -> dict[str, Any]:
    """Agent config with json_mode enabled and compiled schema."""
    return {
        "model_name": "test-model",
        "temperature": 0.7,
        "max_tokens": 100,
        "json_mode": True,
        "compiled_schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
        "prompt": "You are helpful",
    }


@pytest.fixture
def sample_agent_config_no_json_mode() -> dict[str, Any]:
    """Agent config with json_mode disabled (plain text output)."""
    return {
        "model_name": "test-model",
        "temperature": 0.7,
        "max_tokens": 100,
        "json_mode": False,
        "prompt": "You are helpful",
    }


def wire_batch_disposition_delegate(backend: MagicMock) -> None:
    """Wire ``set_dispositions_batch`` to forward calls to ``set_disposition``.

    Use this on mock backends whose tests assert on per-record
    ``set_disposition`` calls, since production code now batches
    dispositions via ``set_dispositions_batch``.
    """

    def _delegate(dispositions: list) -> None:
        for action_name, record_id, disposition, reason, rp, snapshot, detail in dispositions:
            kwargs: dict = {}
            if reason is not None:
                kwargs["reason"] = reason
            if rp is not None:
                kwargs["relative_path"] = rp
            if snapshot is not None or detail is not None:
                kwargs["input_snapshot"] = snapshot
                kwargs["detail"] = detail
            backend.set_disposition(action_name, record_id, disposition, **kwargs)

    backend.set_dispositions_batch = MagicMock(side_effect=_delegate)


@pytest.fixture(autouse=True)
def _reset_global_singletons():
    """Prevent singleton state from leaking between tests."""
    from agent_actions.logging.factory import LoggerFactory
    from agent_actions.utils.correlation.version_id import VersionIdGenerator
    from agent_actions.utils.path_utils import reset_path_manager

    reset_path_manager()
    LoggerFactory.reset()
    VersionIdGenerator.clear()
    yield
    reset_path_manager()
    LoggerFactory.reset()  # cascades to EventManager.reset()
    VersionIdGenerator.clear()

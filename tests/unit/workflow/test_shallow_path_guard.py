"""Regression tests for path-depth bounds checks.

Task 20: .parents[N] on shallow paths must raise ValueError, not IndexError.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.models import (
    WorkflowMetadata,
    WorkflowPaths,
    WorkflowRuntimeConfig,
)


def _make_workflow_config(constructor_path: str) -> WorkflowRuntimeConfig:
    return WorkflowRuntimeConfig(
        paths=WorkflowPaths(
            constructor_path=constructor_path,
            user_code_path=None,
            default_path="defaults.yml",
        ),
        use_tools=False,
    )


def _make_metadata(agent_name: str = "test_agent") -> WorkflowMetadata:
    return WorkflowMetadata(
        agent_name=agent_name,
        execution_order=[],
        action_indices={},
        action_configs={},
    )


# ── service_init.initialize_storage_backend ─────────────────────────────


class TestInitializeStorageBackendShallowPath:
    """initialize_storage_backend must reject paths too shallow for parents[1]."""

    @pytest.mark.parametrize(
        "shallow_path",
        ["agent.yml", ""],
        ids=["single-component", "empty-string"],
    )
    def test_shallow_path_raises_valueerror(self, shallow_path):
        from agent_actions.workflow.service_init import initialize_storage_backend

        config = _make_workflow_config(shallow_path)
        with pytest.raises(ValueError, match="too shallow"):
            initialize_storage_backend(config, _make_metadata(), MagicMock())

    def test_boundary_depth_passes(self, tmp_path):
        """a/b.yml has exactly 2 parents — parents[1] should succeed (no off-by-one)."""
        from agent_actions.workflow.service_init import initialize_storage_backend

        config = _make_workflow_config("a/b.yml")

        with patch("agent_actions.workflow.service_init.get_storage_backend") as mock_backend:
            mock_backend.return_value.initialize.return_value = None
            initialize_storage_backend(config, _make_metadata(), MagicMock())
            mock_backend.assert_called_once_with(
                workflow_path=str(Path("a/b.yml").parents[1]),
                workflow_name="test_agent",
                backend_type="sqlite",
            )

    def test_deep_path_derives_correct_workflow_dir(self, tmp_path):
        """A deep path should derive the correct workflow_dir via parents[1]."""
        from agent_actions.workflow.service_init import initialize_storage_backend

        config_file = tmp_path / "workflows" / "my_wf" / "agent_config" / "my_wf.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("name: test")

        config = _make_workflow_config(str(config_file))
        expected_workflow_dir = str(config_file.parents[1])

        with patch("agent_actions.workflow.service_init.get_storage_backend") as mock_backend:
            mock_backend.return_value.initialize.return_value = None
            initialize_storage_backend(config, _make_metadata("my_wf"), MagicMock())
            mock_backend.assert_called_once_with(
                workflow_path=expected_workflow_dir,
                workflow_name="my_wf",
                backend_type="sqlite",
            )

"""Tests for OutputHandler.save_main_output().

Regression coverage for Task 1: UnboundLocalError when relative_to() raises ValueError.
"""

from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.llm.realtime.output import OutputHandler


class TestSaveMainOutputUnboundLocal:
    """Verify save_main_output raises AgentActionsError (not UnboundLocalError)
    when the file_path is not relative to base_directory."""

    def test_non_relative_path_raises_agent_actions_error(self):
        handler = OutputHandler()
        with pytest.raises(AgentActionsError, match="Error saving main output") as exc_info:
            handler.save_main_output(
                data=[{"a": 1}],
                file_path="/not/relative",
                base_directory="/other/path",
                output_directory="/output",
            )
        assert exc_info.value.context["output_file_path"] == "unknown"
        assert exc_info.value.context["file_path"] == "/not/relative"

    def test_non_relative_path_preserves_cause(self):
        handler = OutputHandler()
        with pytest.raises(AgentActionsError) as exc_info:
            handler.save_main_output(
                data=[{"a": 1}],
                file_path="/not/relative",
                base_directory="/other/path",
                output_directory="/output",
            )
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_oserror_after_path_resolution_includes_output_path(self, tmp_path):
        """OSError handler includes the resolved output_file_path (truthy path)."""
        handler = OutputHandler()
        base = tmp_path / "base"
        base.mkdir()
        src = base / "input.json"
        src.touch()

        with (
            patch.object(
                handler, "_ensure_directory_exists", side_effect=PermissionError("denied")
            ),
            pytest.raises(AgentActionsError, match="IOError saving main output") as exc_info,
        ):
            handler.save_main_output(
                data=[{"a": 1}],
                file_path=str(src),
                base_directory=str(base),
                output_directory=str(tmp_path / "out"),
            )
        assert exc_info.value.context["output_file_path"] != "unknown"
        assert "input.json" in exc_info.value.context["output_file_path"]
        assert isinstance(exc_info.value.__cause__, PermissionError)

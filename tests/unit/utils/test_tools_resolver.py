"""Regression tests for A-2: path traversal prevention in tools_resolver."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent_actions.errors import ConfigValidationError
from agent_actions.utils.tools_resolver import resolve_tools_path


def _make_tool_config(file_path: str) -> dict:
    return {
        "tools": [
            {
                "type": "function",
                "function": {"file": file_path},
            }
        ]
    }


class TestToolsResolverPathTraversal:
    def test_absolute_path_outside_project_raises(self, tmp_path):
        """An absolute path outside project root must raise ConfigValidationError."""
        evil_file = tmp_path / "evil.yaml"
        evil_file.write_text("module_path: evil.module")

        # Patch project root to a different directory so the path is definitely outside
        with patch(
            "agent_actions.utils.tools_resolver.find_project_root",
            return_value=Path("/nonexistent/project/root"),
        ):
            with patch(
                "agent_actions.utils.tools_resolver.Path.cwd",
                return_value=Path("/nonexistent/project/root"),
            ):
                with pytest.raises(ConfigValidationError, match="path traversal"):
                    resolve_tools_path(_make_tool_config(str(evil_file)))

    def test_symlink_outside_project_raises(self, tmp_path):
        """A symlink pointing outside the project root must raise ConfigValidationError."""
        # Create a real file outside the "project"
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        real_file = outside_dir / "secret.yaml"
        real_file.write_text("module_path: bad.module")

        # Create a "project" directory with a symlink pointing outside
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "agent_actions.yml").write_text("")
        symlink = project_dir / "tools" / "link.yaml"
        symlink.parent.mkdir()
        symlink.symlink_to(real_file)

        with patch(
            "agent_actions.utils.tools_resolver.find_project_root",
            return_value=project_dir,
        ):
            with pytest.raises(ConfigValidationError, match="path traversal"):
                resolve_tools_path(_make_tool_config(str(symlink)))

    def test_valid_path_inside_project_succeeds(self, tmp_path):
        """A valid tool file inside the project root is loaded normally."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "agent_actions.yml").write_text("")
        tools_dir = project_dir / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "my_tools.yaml"
        tool_file.write_text(yaml.dump({"module_path": "my.module"}))

        with patch(
            "agent_actions.utils.tools_resolver.find_project_root",
            return_value=project_dir,
        ):
            result = resolve_tools_path(_make_tool_config(str(tool_file)))

        assert result == "my.module"

    def test_dotdot_relative_path_raises(self, tmp_path):
        """../ relative path that resolves outside project root raises ConfigValidationError."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        evil_file = outside_dir / "evil.yaml"
        evil_file.write_text("module_path: evil.module")

        # Construct a relative ../ path from within project_dir that escapes it
        relative_path = str(project_dir / ".." / "outside" / "evil.yaml")

        with patch(
            "agent_actions.utils.tools_resolver.find_project_root",
            return_value=project_dir,
        ):
            with pytest.raises(ConfigValidationError, match="path traversal"):
                resolve_tools_path(_make_tool_config(relative_path))

    def test_cwd_fallback_when_no_project_root(self, tmp_path):
        """When find_project_root() returns None, cwd is used as the security boundary."""
        tool_file = tmp_path / "tool.yaml"
        tool_file.write_text(yaml.dump({"module_path": "cwd.module"}))

        with patch(
            "agent_actions.utils.tools_resolver.find_project_root",
            return_value=None,
        ):
            with patch(
                "agent_actions.utils.tools_resolver.Path.cwd",
                return_value=tmp_path,
            ):
                result = resolve_tools_path(_make_tool_config(str(tool_file)))

        assert result == "cwd.module"

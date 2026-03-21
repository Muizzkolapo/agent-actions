"""Tests for resolve_project_root and get_tool_dirs utilities."""

from pathlib import Path
from unittest.mock import patch

from agent_actions.config.path_config import get_tool_dirs, resolve_project_root
from agent_actions.errors import ConfigValidationError


class TestResolveProjectRoot:
    """resolve_project_root returns explicit path or cwd fallback."""

    def test_returns_explicit_path(self, tmp_path: Path):
        assert resolve_project_root(tmp_path) == tmp_path

    def test_returns_cwd_when_none(self):
        result = resolve_project_root(None)
        assert result == Path.cwd()

    def test_returns_cwd_when_omitted(self):
        result = resolve_project_root()
        assert result == Path.cwd()


class TestGetToolDirs:
    """get_tool_dirs reads tool_path from project config."""

    def test_returns_default_when_no_config(self, tmp_path: Path):
        """No agent_actions.yml → default ["tools"]."""
        assert get_tool_dirs(tmp_path) == ["tools"]

    def test_returns_default_when_key_absent(self, tmp_path: Path):
        """Config exists but tool_path key missing → default ["tools"]."""
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        assert get_tool_dirs(tmp_path) == ["tools"]

    def test_returns_string_as_list(self, tmp_path: Path):
        """tool_path: my_tools → ["my_tools"]."""
        (tmp_path / "agent_actions.yml").write_text("tool_path: my_tools\n")
        assert get_tool_dirs(tmp_path) == ["my_tools"]

    def test_returns_list_as_list(self, tmp_path: Path):
        """tool_path: [tools, extra_tools] → ["tools", "extra_tools"]."""
        (tmp_path / "agent_actions.yml").write_text("tool_path:\n  - tools\n  - extra_tools\n")
        assert get_tool_dirs(tmp_path) == ["tools", "extra_tools"]

    def test_non_iterable_value_coerced_to_list(self, tmp_path: Path):
        """tool_path: 42 → ["42"] (unexpected type handled gracefully)."""
        (tmp_path / "agent_actions.yml").write_text("tool_path: 42\n")
        assert get_tool_dirs(tmp_path) == ["42"]

    def test_returns_default_on_os_error(self, tmp_path: Path):
        """OSError during config load → default ["tools"]."""
        with patch(
            "agent_actions.config.path_config.load_project_config",
            side_effect=OSError("disk error"),
        ):
            assert get_tool_dirs(tmp_path) == ["tools"]

    def test_returns_default_on_config_validation_error(self, tmp_path: Path):
        """ConfigValidationError during config load → default ["tools"]."""
        with patch(
            "agent_actions.config.path_config.load_project_config",
            side_effect=ConfigValidationError("bad_config", "bad yaml"),
        ):
            assert get_tool_dirs(tmp_path) == ["tools"]

    def test_returns_default_when_tool_path_is_none_explicitly(self, tmp_path: Path):
        """tool_path: null → default ["tools"]."""
        (tmp_path / "agent_actions.yml").write_text("tool_path: null\n")
        assert get_tool_dirs(tmp_path) == ["tools"]

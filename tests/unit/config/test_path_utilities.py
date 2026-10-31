"""Tests for resolve_project_root and get_tool_dirs utilities."""

from pathlib import Path
from unittest.mock import patch

import pytest

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


@pytest.mark.parametrize(
    ("config_text", "expected"),
    [
        pytest.param(None, ["tools"], id="no_file"),
        pytest.param("schema_path: schema\n", ["tools"], id="key_absent"),
        pytest.param("tool_path: my_tools\n", ["my_tools"], id="string"),
        pytest.param(
            "tool_path:\n  - tools\n  - extra_tools\n", ["tools", "extra_tools"], id="list"
        ),
        # an unexpected type is coerced, not refused
        pytest.param("tool_path: 42\n", ["42"], id="int"),
        pytest.param("tool_path: null\n", ["tools"], id="null"),
    ],
)
def test_get_tool_dirs_reads_tool_path(tmp_path: Path, config_text, expected):
    if config_text is not None:
        (tmp_path / "agent_actions.yml").write_text(config_text)
    assert get_tool_dirs(tmp_path) == expected


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(OSError("disk error"), id="os_error"),
        pytest.param(ConfigValidationError("bad_config", "bad yaml"), id="config_validation_error"),
    ],
)
def test_get_tool_dirs_returns_default_when_config_load_fails(tmp_path: Path, error):
    with patch("agent_actions.config.path_config.load_project_config", side_effect=error):
        assert get_tool_dirs(tmp_path) == ["tools"]

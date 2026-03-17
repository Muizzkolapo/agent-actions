"""Regression tests for find_project_root in path_utils and project_root."""

import pytest

from agent_actions.config.paths import PathConfig, PathManager, ProjectRootNotFoundError
from agent_actions.utils import path_utils, project_root


def test_path_utils_find_project_root_no_name_error(tmp_path, monkeypatch):
    """Calling path_utils.find_project_root must not raise NameError."""
    marker = tmp_path / "agent_actions.yml"
    marker.write_text("name: test")

    # Use a fresh PathManager so we don't pollute the singleton
    pm = PathManager(config=PathConfig())
    monkeypatch.setattr(path_utils, "_global_path_manager", pm)

    root = path_utils.find_project_root(start_path=tmp_path)
    assert root == tmp_path


def test_path_utils_find_project_root_finds_marker(tmp_path, monkeypatch):
    """path_utils.find_project_root walks up to find agent_actions.yml."""
    marker = tmp_path / "agent_actions.yml"
    marker.write_text("name: test")
    child = tmp_path / "sub" / "deep"
    child.mkdir(parents=True)

    pm = PathManager(config=PathConfig())
    monkeypatch.setattr(path_utils, "_global_path_manager", pm)

    root = path_utils.find_project_root(start_path=child)
    assert root == tmp_path


def test_project_root_find_project_root_finds_marker(tmp_path):
    """project_root.find_project_root walks up to find agent_actions.yml."""
    marker = tmp_path / "agent_actions.yml"
    marker.write_text("name: test")
    child = tmp_path / "nested"
    child.mkdir()

    root = project_root.find_project_root(start_path=str(child))
    assert root == tmp_path


def test_path_utils_find_project_root_raises_when_no_marker(tmp_path, monkeypatch):
    """path_utils.find_project_root raises ProjectRootNotFoundError, not NameError."""
    pm = PathManager(config=PathConfig())
    monkeypatch.setattr(path_utils, "_global_path_manager", pm)

    with pytest.raises(ProjectRootNotFoundError):
        path_utils.find_project_root(start_path=tmp_path)


def test_project_root_find_project_root_returns_none(tmp_path):
    """project_root.find_project_root returns None when no marker exists."""
    result = project_root.find_project_root(start_path=str(tmp_path))
    assert result is None

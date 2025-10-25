"""Unit tests for project root detection."""
import pytest
from pathlib import Path
import os
from agent_actions.utilities.project_root import find_project_root, ensure_in_project, get_project_root_or_cwd, is_in_project
from agent_actions.shared.exceptions import ProjectNotFoundError

class TestFindProjectRoot:
    """Tests for find_project_root function."""

    def test_find_root_from_subdirectory(self, tmp_path):
        """Test finding project root from nested subdirectory."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        subdir = root / 'a' / 'b' / 'c'
        subdir.mkdir(parents=True)
        assert find_project_root(str(subdir)) == root

    def test_find_root_at_root(self, tmp_path):
        """Test when already at project root."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        assert find_project_root(str(root)) == root

    def test_find_root_not_in_project(self, tmp_path):
        """Test behavior when not in a project."""
        assert find_project_root(str(tmp_path)) is None

    def test_find_root_nested_projects(self, tmp_path):
        """Test finding nearest project in nested structure."""
        outer = tmp_path / 'outer'
        outer.mkdir()
        (outer / 'agent_actions.yml').touch()
        inner = outer / 'submodule'
        inner.mkdir()
        (inner / 'agent_actions.yml').touch()
        subdir = inner / 'src'
        subdir.mkdir()
        assert find_project_root(str(subdir)) == inner

    def test_find_root_default_cwd(self, tmp_path, monkeypatch):
        """Test using current working directory by default."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        monkeypatch.chdir(root)
        assert find_project_root() == root

    def test_find_root_with_symlinks(self, tmp_path):
        """Test that symlinks are resolved correctly."""
        project = tmp_path / 'project'
        project.mkdir()
        (project / 'agent_actions.yml').touch()
        subdir = project / 'subdir'
        subdir.mkdir()
        assert find_project_root(str(subdir)) == project

    def test_find_root_multiple_levels(self, tmp_path):
        """Test finding root from various depths."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        level1 = root / 'level1'
        level1.mkdir()
        assert find_project_root(str(level1)) == root
        level2 = level1 / 'level2'
        level2.mkdir()
        assert find_project_root(str(level2)) == root
        deep = root / 'a' / 'b' / 'c' / 'd' / 'e'
        deep.mkdir(parents=True)
        assert find_project_root(str(deep)) == root

class TestEnsureInProject:
    """Tests for ensure_in_project function."""

    def test_ensure_in_project_success(self, tmp_path, monkeypatch):
        """Test successful project detection."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        monkeypatch.chdir(root)
        assert ensure_in_project() == root

    def test_ensure_in_project_from_subdirectory(self, tmp_path, monkeypatch):
        """Test successful detection from subdirectory."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        subdir = root / 'src' / 'utils'
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        assert ensure_in_project() == root

    def test_ensure_in_project_failure(self, tmp_path, monkeypatch):
        """Test exception when not in project."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ProjectNotFoundError) as exc_info:
            ensure_in_project()
        assert 'agent_actions.yml' in str(exc_info.value.context)
        assert 'solution_1' in exc_info.value.context
        assert 'solution_2' in exc_info.value.context

    def test_ensure_in_project_error_context(self, tmp_path, monkeypatch):
        """Test that error context contains expected fields."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ProjectNotFoundError) as exc_info:
            ensure_in_project()
        context = exc_info.value.context
        assert context['marker_file'] == 'agent_actions.yml'
        assert context['search_path'] == str(tmp_path)
        assert 'Navigate to your agent-actions project directory' in context['solution_1']
        assert 'agent-actions init' in context['solution_2']

class TestGetProjectRootOrCwd:
    """Tests for get_project_root_or_cwd function."""

    def test_returns_root_when_in_project(self, tmp_path, monkeypatch):
        """Test returns project root when in project."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        subdir = root / 'src'
        subdir.mkdir()
        monkeypatch.chdir(subdir)
        assert get_project_root_or_cwd() == root

    def test_returns_cwd_when_not_in_project(self, tmp_path, monkeypatch):
        """Test returns CWD when not in project."""
        monkeypatch.chdir(tmp_path)
        result = get_project_root_or_cwd()
        assert result.resolve() == tmp_path.resolve()

    def test_returns_root_from_deep_subdirectory(self, tmp_path, monkeypatch):
        """Test returns root from deeply nested directory."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        deep = root / 'a' / 'b' / 'c'
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        assert get_project_root_or_cwd() == root

class TestIsInProject:
    """Tests for is_in_project function."""

    def test_true_when_in_project(self, tmp_path, monkeypatch):
        """Test returns True when in project."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        monkeypatch.chdir(root)
        assert is_in_project() is True

    def test_false_when_not_in_project(self, tmp_path, monkeypatch):
        """Test returns False when not in project."""
        monkeypatch.chdir(tmp_path)
        assert is_in_project() is False

    def test_true_from_subdirectory(self, tmp_path, monkeypatch):
        """Test returns True from subdirectory."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        subdir = root / 'src' / 'utils'
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        assert is_in_project() is True

    def test_false_from_parent_directory(self, tmp_path, monkeypatch):
        """Test returns False from parent of project."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        monkeypatch.chdir(tmp_path)
        assert is_in_project() is False

class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_marker_file_is_directory_not_file(self, tmp_path):
        """Test that directories named agent_actions.yml are ignored."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').mkdir()
        assert find_project_root(str(root)) is None

    def test_empty_directory(self, tmp_path):
        """Test behavior in empty directory."""
        empty = tmp_path / 'empty'
        empty.mkdir()
        assert find_project_root(str(empty)) is None
        assert is_in_project() is False

    def test_very_deep_nesting(self, tmp_path):
        """Test with very deep directory nesting."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        current = root
        for i in range(20):
            current = current / f'level{i}'
        current.mkdir(parents=True)
        assert find_project_root(str(current)) == root
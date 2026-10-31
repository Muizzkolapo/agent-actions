"""Tests for defensive branches in project root discovery."""

from pathlib import Path
from unittest.mock import patch

from agent_actions.utils import project_root
from agent_actions.utils.project_root import find_project_root


class TestStartPathNoneDefault:
    """start_path=None should default to os.getcwd()."""

    def test_none_start_path_uses_cwd(self, tmp_path, monkeypatch):
        (tmp_path / "agent_actions.yml").write_text("name: test")
        monkeypatch.chdir(tmp_path)
        result = find_project_root(start_path=None)
        assert result == tmp_path


class TestMaxParentLevelsGuard:
    """MAX_PARENT_LEVELS prevents infinite traversal."""

    def test_search_stops_at_max_depth(self, tmp_path):
        """When marker is above MAX_PARENT_LEVELS, returns None."""
        # We can't create 100+ directories in practice, so mock the limit
        with patch.object(project_root, "MAX_PARENT_LEVELS", 2):
            # Create a 3-deep nesting: tmp_path/a/b/c
            deep = tmp_path / "a" / "b" / "c"
            deep.mkdir(parents=True)
            # Place marker at tmp_path (3 levels up from c)
            (tmp_path / "agent_actions.yml").write_text("name: test")

            # With limit of 2, search from 'c' should not reach tmp_path
            result = find_project_root(start_path=str(deep))
            assert result is None

    def test_search_succeeds_within_limit(self, tmp_path):
        """When marker is within MAX_PARENT_LEVELS, it is found."""
        with patch.object(project_root, "MAX_PARENT_LEVELS", 5):
            deep = tmp_path / "a" / "b"
            deep.mkdir(parents=True)
            (tmp_path / "agent_actions.yml").write_text("name: test")

            result = find_project_root(start_path=str(deep))
            assert result == tmp_path


class TestPermissionErrorHandling:
    """PermissionError on marker.exists() is caught and search continues."""

    def test_permission_error_skipped(self, tmp_path):
        """If a parent dir raises PermissionError, search continues upward."""
        child = tmp_path / "sub"
        child.mkdir()
        (tmp_path / "agent_actions.yml").write_text("name: test")

        original_exists = Path.exists

        def patched_exists(self):
            # Raise PermissionError only for the child marker check
            if str(self) == str(child / "agent_actions.yml"):
                raise PermissionError("denied")
            return original_exists(self)

        with patch.object(Path, "exists", patched_exists):
            result = find_project_root(start_path=str(child))
            assert result == tmp_path


class TestMarkerIsDirectory:
    """agent_actions.yml that is a directory (not a file) should be rejected."""

    def test_directory_marker_rejected(self, tmp_path):
        """If agent_actions.yml is a directory, find_project_root does not match it."""
        # Create agent_actions.yml as a directory
        (tmp_path / "agent_actions.yml").mkdir()

        result = find_project_root(start_path=str(tmp_path))
        assert result is None

    def test_directory_marker_skipped_file_marker_found(self, tmp_path):
        """Dir marker in child is skipped; file marker in parent is found."""
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / "agent_actions.yml").write_text("name: test")

        child = parent / "child"
        child.mkdir()
        # Create agent_actions.yml as a directory in child
        (child / "agent_actions.yml").mkdir()

        result = find_project_root(start_path=str(child))
        assert result == parent


class TestLspFindProjectRootFallback:
    """LSP indexer find_project_root downward glob and fallback paths."""

    def test_downward_glob_finds_nested_project(self, tmp_path):
        """Downward glob finds marker in subdirectory."""
        from agent_actions.tooling.lsp.indexer import find_project_root as lsp_find

        proj = tmp_path / "nested_project"
        proj.mkdir()
        (proj / "agent_actions.yml").write_text("name: test")

        result = lsp_find(tmp_path)
        assert result == proj

    def test_fallback_returns_none_when_no_marker(self, tmp_path):
        """When no marker exists anywhere, find_project_root returns None (T2-6)."""
        from agent_actions.tooling.lsp.indexer import find_project_root as lsp_find

        empty = tmp_path / "empty_dir"
        empty.mkdir()

        result = lsp_find(empty)
        assert result is None

    def test_file_path_with_no_marker_returns_none(self, tmp_path):
        """When start_path is a file with no marker anywhere, returns None (T2-6)."""
        from agent_actions.tooling.lsp.indexer import find_project_root as lsp_find

        some_file = tmp_path / "somefile.py"
        some_file.write_text("# code")

        result = lsp_find(some_file)
        assert result is None

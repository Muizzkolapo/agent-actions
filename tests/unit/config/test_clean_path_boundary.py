"""Tests for clean_path() project-boundary enforcement."""

import pytest

from agent_actions.config.paths import PathConfig, PathManager


@pytest.fixture
def path_manager(tmp_path):
    """Create a PathManager rooted at a temporary directory with a marker file."""
    marker = tmp_path / "agent_actions.yml"
    marker.write_text("name: test")
    return PathManager(config=PathConfig(), project_root=tmp_path)


class TestCleanPathBoundary:
    def test_path_inside_project_succeeds(self, path_manager, tmp_path):
        """Deleting a file inside the project root should succeed."""
        target = tmp_path / "some_file.txt"
        target.write_text("delete me")
        assert target.exists()

        result = path_manager.clean_path(target)
        assert result is True
        assert not target.exists()

    def test_path_outside_project_raises(self, path_manager, tmp_path):
        """Deleting a file outside the project root should raise ValueError."""
        outside = tmp_path.parent / "outside_file.txt"
        outside.write_text("do not delete")

        try:
            with pytest.raises(ValueError, match="Refusing to delete path outside project root"):
                path_manager.clean_path(outside)
        finally:
            outside.unlink(missing_ok=True)

    def test_path_with_dotdot_escape_raises(self, path_manager, tmp_path):
        """Path using .. to escape project root should raise ValueError."""
        escape_path = tmp_path / "subdir" / ".." / ".." / "escaped.txt"

        with pytest.raises(ValueError, match="Refusing to delete path outside project root"):
            path_manager.clean_path(escape_path)

    def test_symlink_escape_raises(self, path_manager, tmp_path):
        """Symlink inside project pointing outside should raise ValueError.

        normalize_path() calls .resolve() which follows symlinks, so the
        resolved target falls outside the project root.
        """
        outside_file = tmp_path.parent / "outside_target.txt"
        outside_file.write_text("do not delete")
        symlink = tmp_path / "sneaky_link"

        try:
            symlink.symlink_to(outside_file)
            with pytest.raises(ValueError, match="Refusing to delete path outside project root"):
                path_manager.clean_path(symlink)
            # Verify the outside file was NOT deleted
            assert outside_file.exists()
        finally:
            symlink.unlink(missing_ok=True)
            outside_file.unlink(missing_ok=True)

    def test_directory_inside_project_succeeds(self, path_manager, tmp_path):
        """Deleting a directory inside the project root should succeed."""
        target_dir = tmp_path / "subdir"
        target_dir.mkdir()
        (target_dir / "file.txt").write_text("content")

        result = path_manager.clean_path(target_dir, recursive=True)
        assert result is True
        assert not target_dir.exists()

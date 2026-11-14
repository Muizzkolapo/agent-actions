"""Project-tree searches skip directories that cannot hold user content."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_actions.utils.file_handler import FileHandler, find_project_dirs


def _make_venv(root: Path, name: str = ".venv") -> Path:
    venv = root / name
    (venv / "lib").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    return venv


def _named_overview(name: str) -> bool:
    return name == "overview"


class TestFindProjectDirsSkipsNonProjectDirs:
    def test_dir_only_inside_a_virtualenv_is_not_found(self, tmp_path):
        """A dependency's folder is not the user's."""
        venv = _make_venv(tmp_path)
        (venv / "lib" / "overview").mkdir()

        assert find_project_dirs(tmp_path, _named_overview) == []

    def test_dir_only_inside_git_or_node_modules_is_not_found(self, tmp_path):
        (tmp_path / ".git" / "objects" / "overview").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "overview").mkdir(parents=True)

        assert find_project_dirs(tmp_path, _named_overview) == []

    def test_project_dir_is_still_found(self, tmp_path):
        """Pruning must not narrow the search within the user's own tree."""
        target = tmp_path / "agent_workflow" / "wf" / "overview"
        target.mkdir(parents=True)

        assert find_project_dirs(tmp_path, _named_overview) == [target]

    def test_only_the_project_copy_is_found_beside_a_same_named_dir_in_a_virtualenv(self, tmp_path):
        venv = _make_venv(tmp_path)
        (venv / "lib" / "overview").mkdir()
        target = tmp_path / "prompt_store" / "overview"
        target.mkdir(parents=True)

        assert find_project_dirs(tmp_path, _named_overview) == [target]


class TestVirtualenvDetectionIsByMarkerNotName:
    def test_virtualenv_under_an_arbitrary_name_is_skipped(self, tmp_path):
        """Projects name their env anything; pyvenv.cfg is what identifies it."""
        venv = _make_venv(tmp_path, name=".myproject_env")
        (venv / "lib" / "overview").mkdir()

        assert find_project_dirs(tmp_path, _named_overview) == []

    def test_directory_named_venv_without_the_marker_is_still_searched(self, tmp_path):
        """A plain directory called venv is the user's, not an environment."""
        target = tmp_path / "venv" / "overview"
        target.mkdir(parents=True)

        assert find_project_dirs(tmp_path, _named_overview) == [target]

    def test_unlisted_dot_directory_is_still_searched(self, tmp_path):
        """Only the named dirs and virtualenvs are skipped, not every dot-directory."""
        target = tmp_path / ".claude" / "skills" / "overview"
        target.mkdir(parents=True)

        assert find_project_dirs(tmp_path, _named_overview) == [target]


class TestUnreadableDirectoriesDoNotBreakTheSearch:
    @pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory permissions")
    def test_directory_the_user_cannot_read_is_skipped_not_raised(self, tmp_path):
        """The venv probe stats inside every candidate dir; an unreadable one must not crash."""
        target = tmp_path / "prompt_store" / "overview"
        target.mkdir(parents=True)
        restricted = tmp_path / "restricted"
        restricted.mkdir()
        restricted.chmod(0o000)
        try:
            assert find_project_dirs(tmp_path, _named_overview) == [target]
        finally:
            restricted.chmod(0o755)


class TestFolderSearchesSkipNonProjectDirs:
    def test_agent_config_inside_a_virtualenv_is_not_a_project_agent(self, tmp_path):
        """A packaged example shipped by a dependency is not the user's workflow."""
        venv = _make_venv(tmp_path)
        (venv / "lib" / "vendored" / "agent_config").mkdir(parents=True)

        assert FileHandler.find_specific_folder(str(tmp_path), "vendored", "agent_config") is None
        assert (
            FileHandler.find_all_specific_folders(str(tmp_path), "vendored", "agent_config") == []
        )

    def test_project_agent_folder_is_still_found(self, tmp_path):
        wf = tmp_path / "agent_workflow" / "my_wf"
        (wf / "agent_config").mkdir(parents=True)

        found = FileHandler.find_specific_folder(str(tmp_path), "my_wf", "agent_config")
        assert found == str(wf / "agent_config")

"""Project-tree searches skip directories that cannot hold user content."""

from __future__ import annotations

from pathlib import Path

from agent_actions.utils.file_handler import FileHandler


def _make_venv(root: Path, name: str = ".venv") -> Path:
    venv = root / name
    (venv / "lib").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    return venv


class TestFindFileInDirectorySkipsNonProjectDirs:
    def test_file_only_inside_a_virtualenv_is_not_found(self, tmp_path):
        """A dependency's markdown is not the user's prompt file."""
        venv = _make_venv(tmp_path)
        (venv / "lib" / "overview.md").write_text("dependency docs")

        assert FileHandler.find_file_in_directory(str(tmp_path), "overview.md") is None

    def test_file_only_inside_git_or_node_modules_is_not_found(self, tmp_path):
        (tmp_path / ".git" / "objects").mkdir(parents=True)
        (tmp_path / ".git" / "objects" / "notes.md").write_text("vcs internals")
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "readme.md").write_text("js dep")

        assert FileHandler.find_file_in_directory(str(tmp_path), "notes.md") is None
        assert FileHandler.find_file_in_directory(str(tmp_path), "readme.md") is None

    def test_project_file_is_still_found(self, tmp_path):
        """Pruning must not narrow the search within the user's own tree."""
        nested = tmp_path / "agent_workflow" / "wf" / "prompt_store"
        nested.mkdir(parents=True)
        target = nested / "overview.md"
        target.write_text("real prompt")

        assert FileHandler.find_file_in_directory(str(tmp_path), "overview.md") == str(target)

    def test_project_copy_wins_over_a_same_named_file_in_a_virtualenv(self, tmp_path):
        """The collision the unpruned walk resolved by filesystem order."""
        venv = _make_venv(tmp_path)
        (venv / "lib" / "overview.md").write_text("dependency docs")
        prompts = tmp_path / "prompt_store"
        prompts.mkdir()
        target = prompts / "overview.md"
        target.write_text("real prompt")

        assert FileHandler.find_file_in_directory(str(tmp_path), "overview.md") == str(target)


class TestVirtualenvDetectionIsByMarkerNotName:
    def test_virtualenv_under_an_arbitrary_name_is_skipped(self, tmp_path):
        """Projects name their env anything; pyvenv.cfg is what identifies it."""
        venv = _make_venv(tmp_path, name=".myproject_env")
        (venv / "lib" / "overview.md").write_text("dependency docs")

        assert FileHandler.find_file_in_directory(str(tmp_path), "overview.md") is None

    def test_directory_named_venv_without_the_marker_is_still_searched(self, tmp_path):
        """A plain directory called venv is the user's, not an environment."""
        plain = tmp_path / "venv"
        plain.mkdir()
        target = plain / "overview.md"
        target.write_text("real prompt")

        assert FileHandler.find_file_in_directory(str(tmp_path), "overview.md") == str(target)

    def test_unlisted_dot_directory_is_still_searched(self, tmp_path):
        """Only the named dirs and virtualenvs are skipped, not every dot-directory."""
        skills = tmp_path / ".claude" / "skills"
        skills.mkdir(parents=True)
        target = skills / "overview.md"
        target.write_text("real prompt")

        assert FileHandler.find_file_in_directory(str(tmp_path), "overview.md") == str(target)


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

"""Tests for LSP resolver — SEED_FILE reference type guard."""

from pathlib import Path
from unittest.mock import MagicMock

from agent_actions.tooling.lsp.models import Location, Reference, ReferenceType
from agent_actions.tooling.lsp.resolver import resolve_reference


def _make_seed_ref(value: str) -> Reference:
    return Reference(
        type=ReferenceType.SEED_FILE,
        value=value,
        location=Location(file_path=Path(), line=0, column=0),
        raw_text=f"$file:{value}",
    )


class TestSeedFileResolver:
    """resolve_reference for SEED_FILE should guard .parent.parent traversal."""

    def test_resolves_when_inside_agent_config(self, tmp_path):
        """current_file inside agent_config/ — should find workflow seed_data."""
        workflow = tmp_path / "my_workflow"
        config_dir = workflow / "agent_config"
        config_dir.mkdir(parents=True)
        seed_dir = workflow / "seed_data"
        seed_dir.mkdir(parents=True)
        seed_file = seed_dir / "data.csv"
        seed_file.write_text("a,b,c")

        current_file = config_dir / "agent.yml"
        current_file.write_text("name: test")

        index = MagicMock()
        index.root = tmp_path / "nonexistent_root"  # project-level seed_data doesn't exist
        index.root.mkdir(parents=True, exist_ok=True)

        ref = _make_seed_ref("data.csv")
        result = resolve_reference(ref, index, current_file=current_file)

        assert result is not None
        assert result.file_path == seed_file

    def test_skips_when_not_inside_agent_config(self, tmp_path):
        """current_file NOT inside agent_config/ — should skip workflow seed lookup."""
        # Put current_file at root level (parent.name != "agent_config")
        root_file = tmp_path / "some_file.yml"
        root_file.write_text("name: test")

        index = MagicMock()
        index.root = tmp_path / "nonexistent_root"
        index.root.mkdir(parents=True, exist_ok=True)

        ref = _make_seed_ref("data.csv")
        result = resolve_reference(ref, index, current_file=root_file)

        # Should not crash and should return None (no seed_data found)
        assert result is None

    def test_resolves_from_nested_agent_config_subdir(self, tmp_path):
        """current_file in agent_config/versions/ — should still find workflow seed_data."""
        workflow = tmp_path / "my_workflow"
        versions_dir = workflow / "agent_config" / "versions"
        versions_dir.mkdir(parents=True)
        seed_dir = workflow / "seed_data"
        seed_dir.mkdir(parents=True)
        seed_file = seed_dir / "data.csv"
        seed_file.write_text("a,b,c")

        current_file = versions_dir / "agent_v2.yml"
        current_file.write_text("name: test")

        index = MagicMock()
        index.root = tmp_path / "nonexistent_root"
        index.root.mkdir(parents=True, exist_ok=True)

        ref = _make_seed_ref("data.csv")
        result = resolve_reference(ref, index, current_file=current_file)

        assert result is not None
        assert result.file_path == seed_file

    def test_falls_back_to_project_seed_data(self, tmp_path):
        """When project-level seed_data exists, use it regardless of current_file location."""
        project_seed = tmp_path / "seed_data"
        project_seed.mkdir()
        seed_file = project_seed / "lookup.json"
        seed_file.write_text("{}")

        index = MagicMock()
        index.root = tmp_path

        ref = _make_seed_ref("lookup.json")
        result = resolve_reference(ref, index, current_file=None)

        assert result is not None
        assert result.file_path == seed_file

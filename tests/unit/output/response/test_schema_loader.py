"""Tests for SchemaLoader schema search behavior."""

import pytest

from agent_actions.output.response.loader import SchemaLoader


def _setup_project(tmp_path, schema_path="schema"):
    """Create a project with agent_actions.yml and schema dir."""
    (tmp_path / "agent_actions.yml").write_text(f"schema_path: {schema_path}\n")
    schema_dir = tmp_path / schema_path
    schema_dir.mkdir(parents=True, exist_ok=True)
    return schema_dir


class TestLoadSchemaRecursive:
    """Tests for SchemaLoader.load_schema() search behavior."""

    def test_flat_schema_found(self, tmp_path):
        schema_dir = _setup_project(tmp_path)
        (schema_dir / "my_schema.yml").write_text("name: my_schema\nfields: []\n")

        result = SchemaLoader.load_schema("my_schema", project_root=tmp_path)
        assert result["name"] == "my_schema"

    def test_subdirectory_schema_found(self, tmp_path):
        schema_dir = _setup_project(tmp_path)
        sub = schema_dir / "my_workflow"
        sub.mkdir()
        (sub / "my_schema.yml").write_text("name: my_schema\nfields: []\n")

        result = SchemaLoader.load_schema("my_schema", project_root=tmp_path)
        assert result["name"] == "my_schema"

    def test_multiple_matches_raises_with_paths(self, tmp_path):
        schema_dir = _setup_project(tmp_path)
        for subdir in ("a", "b"):
            d = schema_dir / subdir
            d.mkdir(parents=True)
            (d / "dup.yml").write_text("name: dup\nfields: []\n")

        with pytest.raises(FileNotFoundError, match="multiple locations"):
            SchemaLoader.load_schema("dup", project_root=tmp_path)

    def test_no_match_raises(self, tmp_path):
        _setup_project(tmp_path)

        with pytest.raises(FileNotFoundError, match="not found"):
            SchemaLoader.load_schema("nonexistent", project_root=tmp_path)

    def test_missing_schema_dir_raises(self, tmp_path):
        """Schema dir doesn't exist — still raises not found."""
        (tmp_path / "agent_actions.yml").write_text("schema_path: nonexistent_dir\n")

        with pytest.raises(FileNotFoundError, match="not found"):
            SchemaLoader.load_schema("anything", project_root=tmp_path)

    def test_flat_takes_priority_is_uniqueness_error(self, tmp_path):
        """Same name in flat and subdirectory is a uniqueness error."""
        schema_dir = _setup_project(tmp_path)
        (schema_dir / "priority.yml").write_text("name: flat_version\nfields: []\n")
        sub = schema_dir / "sub"
        sub.mkdir()
        (sub / "priority.yml").write_text("name: sub_version\nfields: []\n")

        with pytest.raises(FileNotFoundError, match="multiple locations"):
            SchemaLoader.load_schema("priority", project_root=tmp_path)

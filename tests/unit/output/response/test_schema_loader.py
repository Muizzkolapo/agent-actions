"""Tests for SchemaLoader schema search behavior."""

import json

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

    def test_multiple_matches_warns_and_uses_first(self, tmp_path):
        schema_dir = _setup_project(tmp_path)
        for subdir in ("a", "b"):
            d = schema_dir / subdir
            d.mkdir(parents=True)
            (d / "dup.yml").write_text(f"name: dup_{subdir}\nfields: []\n")

        result = SchemaLoader.load_schema("dup", project_root=tmp_path)
        assert result["name"] == "dup_a"  # first alphabetically wins

    def test_no_match_raises(self, tmp_path):
        _setup_project(tmp_path)

        with pytest.raises(FileNotFoundError, match="not found"):
            SchemaLoader.load_schema("nonexistent", project_root=tmp_path)

    def test_missing_schema_dir_raises(self, tmp_path):
        """Schema dir doesn't exist — still raises not found."""
        (tmp_path / "agent_actions.yml").write_text("schema_path: nonexistent_dir\n")

        with pytest.raises(FileNotFoundError, match="not found"):
            SchemaLoader.load_schema("anything", project_root=tmp_path)

    def test_flat_takes_priority_over_subdirectory(self, tmp_path):
        """Same name in flat and subdirectory: flat wins (first found)."""
        schema_dir = _setup_project(tmp_path)
        (schema_dir / "priority.yml").write_text("name: flat_version\nfields: []\n")
        sub = schema_dir / "sub"
        sub.mkdir()
        (sub / "priority.yml").write_text("name: sub_version\nfields: []\n")

        result = SchemaLoader.load_schema("priority", project_root=tmp_path)
        assert result["name"] == "flat_version"

    def test_json_schema_found(self, tmp_path):
        """JSON schema files are discovered and loaded correctly."""
        schema_dir = _setup_project(tmp_path)
        schema = {"name": "json_schema", "fields": []}
        (schema_dir / "my_schema.json").write_text(json.dumps(schema))

        result = SchemaLoader.load_schema("my_schema", project_root=tmp_path)
        assert result["name"] == "json_schema"

    def test_json_and_yml_same_stem_uses_first(self, tmp_path):
        """When both .yml and .json exist for same stem, first alphabetically wins."""
        schema_dir = _setup_project(tmp_path)
        (schema_dir / "dup.yml").write_text("name: yml_version\nfields: []\n")
        schema = {"name": "json_version", "fields": []}
        (schema_dir / "dup.json").write_text(json.dumps(schema))

        result = SchemaLoader.load_schema("dup", project_root=tmp_path)
        # sorted() puts .json before .yml alphabetically, so json wins
        assert result["name"] == "json_version"

"""Tests for SchemaLoader recursive schema search."""

from unittest.mock import patch

import pytest

from agent_actions.errors import SchemaValidationError
from agent_actions.output.response.loader import SchemaLoader


class TestLoadSchemaRecursive:
    """Tests for SchemaLoader.load_schema() recursive search behavior."""

    def test_flat_schema_found(self, tmp_path):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        schema_file = schema_dir / "my_schema.yml"
        schema_file.write_text("name: my_schema\nfields: []\n")

        result = SchemaLoader.load_schema("my_schema", schema_dir=schema_dir)
        assert result["name"] == "my_schema"

    def test_subdirectory_schema_found(self, tmp_path):
        schema_dir = tmp_path / "schema"
        sub = schema_dir / "my_workflow"
        sub.mkdir(parents=True)
        schema_file = sub / "my_schema.yml"
        schema_file.write_text("name: my_schema\nfields: []\n")

        result = SchemaLoader.load_schema("my_schema", schema_dir=schema_dir)
        assert result["name"] == "my_schema"

    def test_multiple_matches_raises_with_paths(self, tmp_path):
        schema_dir = tmp_path / "schema"
        for subdir in ("a", "b"):
            d = schema_dir / subdir
            d.mkdir(parents=True)
            (d / "dup.yml").write_text("name: dup\nfields: []\n")

        with pytest.raises(FileNotFoundError, match="Multiple schema files"):
            SchemaLoader.load_schema("dup", schema_dir=schema_dir)

    def test_no_match_raises(self, tmp_path):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="not found"):
            SchemaLoader.load_schema("nonexistent", schema_dir=schema_dir)

    def test_missing_schema_dir_raises(self, tmp_path):
        schema_dir = tmp_path / "nonexistent_schema"

        with pytest.raises(FileNotFoundError, match="not found"):
            SchemaLoader.load_schema("anything", schema_dir=schema_dir)

    def test_flat_takes_priority_over_subdirectory(self, tmp_path):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        # Flat file
        flat = schema_dir / "priority.yml"
        flat.write_text("name: flat_version\nfields: []\n")
        # Subdirectory file
        sub = schema_dir / "sub"
        sub.mkdir()
        (sub / "priority.yml").write_text("name: sub_version\nfields: []\n")

        result = SchemaLoader.load_schema("priority", schema_dir=schema_dir)
        assert result["name"] == "flat_version"


class TestReturnSchemaErrorHandling:
    """Tests for return_schema() narrowed exception handling."""

    @patch(
        "agent_actions.output.response.loader.FileHandler.get_agent_paths",
        return_value=(None, None),
    )
    def test_raises_on_missing_agent_config_dir(self, _mock):
        """Missing agent_config dir should raise with clear message, not TypeError."""
        with pytest.raises(SchemaValidationError, match="Agent config directory not found"):
            SchemaLoader.return_schema("nonexistent_agent")

    @patch(
        "agent_actions.output.response.loader.FileHandler.find_config_file",
        return_value=None,
    )
    @patch(
        "agent_actions.output.response.loader.FileHandler.get_agent_paths",
        return_value=("/some/path", "/some/io"),
    )
    def test_raises_on_missing_config_file(self, _paths, _find):
        """Missing config file should raise with clear message, not TypeError."""
        with pytest.raises(SchemaValidationError, match="Config file.*not found"):
            SchemaLoader.return_schema("missing_config")

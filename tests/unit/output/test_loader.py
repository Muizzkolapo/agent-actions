"""J-2: Coverage of SchemaLoader — None return from empty YAML and missing-file handling."""

import pytest
import yaml

from agent_actions.output.response.loader import SchemaLoader


def _write_project_config(project_root, schema_folder="schema"):
    """Create an agent_actions.yml with schema_path in the given project root."""
    (project_root / "agent_actions.yml").write_text(f"schema_path: {schema_folder}\n")


class TestSchemaLoaderLoadSchema:
    """SchemaLoader.load_schema() behaviour on missing files."""

    def test_missing_file_raises_file_not_found(self, tmp_path):
        _write_project_config(tmp_path)
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="MySchema"):
            SchemaLoader.load_schema("MySchema", project_root=tmp_path)

    def test_nonexistent_directory_raises_file_not_found(self, tmp_path):
        _write_project_config(tmp_path, schema_folder="does_not_exist")
        with pytest.raises(FileNotFoundError):
            SchemaLoader.load_schema("AnySchema", project_root=tmp_path)

    def test_valid_schema_returns_dict(self, tmp_path):
        _write_project_config(tmp_path)
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        schema_content = {"name": "TestSchema", "fields": [{"id": "result", "type": "string"}]}
        (schema_dir / "TestSchema.yml").write_text(yaml.dump(schema_content))
        result = SchemaLoader.load_schema("TestSchema", project_root=tmp_path)
        assert isinstance(result, dict)
        assert result["name"] == "TestSchema"

    def test_empty_yaml_returns_none(self, tmp_path):
        """An empty YAML file produces yaml.safe_load -> None; loader returns that."""
        _write_project_config(tmp_path)
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "Empty.yml").write_text("")
        result = SchemaLoader.load_schema("Empty", project_root=tmp_path)
        assert result is None

    def test_recursive_search_finds_nested_schema(self, tmp_path):
        _write_project_config(tmp_path)
        schema_dir = tmp_path / "schema"
        sub = schema_dir / "sub"
        sub.mkdir(parents=True)
        schema_content = {"name": "NestedSchema", "fields": []}
        (sub / "NestedSchema.yml").write_text(yaml.dump(schema_content))
        result = SchemaLoader.load_schema("NestedSchema", project_root=tmp_path)
        assert isinstance(result, dict)
        assert result["name"] == "NestedSchema"

    def test_multiple_matches_uses_first_found(self, tmp_path):
        """Multiple files with same name: first found wins (warns, does not raise)."""
        _write_project_config(tmp_path)
        schema_dir = tmp_path / "schema"
        sub1 = schema_dir / "sub1"
        sub2 = schema_dir / "sub2"
        sub1.mkdir(parents=True)
        sub2.mkdir(parents=True)
        (sub1 / "Dup.yml").write_text("name: Dup1\n")
        (sub2 / "Dup.yml").write_text("name: Dup2\n")
        result = SchemaLoader.load_schema("Dup", project_root=tmp_path)
        assert result["name"] == "Dup1"  # first alphabetically


class TestSchemaLoaderConstructSchemaFromDict:
    """construct_schema_from_dict builds unified schema from a type dict."""

    def test_simple_fields(self):
        result = SchemaLoader.construct_schema_from_dict({"name": "string", "age": "integer"})
        assert result["name"] == "InlineSchema"
        field_ids = [f["id"] for f in result["fields"]]
        assert "name" in field_ids
        assert "age" in field_ids

    def test_required_field_marker(self):
        result = SchemaLoader.construct_schema_from_dict({"title": "string!"})
        field = result["fields"][0]
        assert field["required"] is True

    def test_array_type(self):
        result = SchemaLoader.construct_schema_from_dict({"tags": "array[string]"})
        field = result["fields"][0]
        assert field["type"] == "array"
        assert field["items"]["type"] == "string"

    def test_empty_dict_returns_empty_fields(self):
        result = SchemaLoader.construct_schema_from_dict({})
        assert result["name"] == "InlineSchema"
        assert result["fields"] == []

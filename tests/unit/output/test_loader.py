"""J-2: Coverage of SchemaLoader — None return from empty YAML and missing-file handling."""

import pytest
import yaml

from agent_actions.output.response.loader import SchemaLoader


class TestSchemaLoaderLoadSchema:
    """SchemaLoader.load_schema() behaviour on missing files."""

    def test_missing_file_raises_file_not_found(self, tmp_path):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="MySchema.yml"):
            SchemaLoader.load_schema("MySchema", schema_dir=schema_dir)

    def test_nonexistent_directory_raises_file_not_found(self, tmp_path):
        schema_dir = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError):
            SchemaLoader.load_schema("AnySchema", schema_dir=schema_dir)

    def test_valid_schema_returns_dict(self, tmp_path):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        schema_content = {"name": "TestSchema", "fields": [{"id": "result", "type": "string"}]}
        (schema_dir / "TestSchema.yml").write_text(yaml.dump(schema_content))
        result = SchemaLoader.load_schema("TestSchema", schema_dir=schema_dir)
        assert isinstance(result, dict)
        assert result["name"] == "TestSchema"

    def test_empty_yaml_returns_none(self, tmp_path):
        """An empty YAML file produces yaml.safe_load -> None; loader returns that."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "Empty.yml").write_text("")
        result = SchemaLoader.load_schema("Empty", schema_dir=schema_dir)
        assert result is None

    def test_recursive_search_finds_nested_schema(self, tmp_path):
        schema_dir = tmp_path / "schema"
        sub = schema_dir / "sub"
        sub.mkdir(parents=True)
        schema_content = {"name": "NestedSchema", "fields": []}
        (sub / "NestedSchema.yml").write_text(yaml.dump(schema_content))
        result = SchemaLoader.load_schema("NestedSchema", schema_dir=schema_dir)
        assert isinstance(result, dict)
        assert result["name"] == "NestedSchema"

    def test_multiple_matches_raises_file_not_found(self, tmp_path):
        """Multiple files with same name cause FileNotFoundError with disambiguation hint."""
        schema_dir = tmp_path / "schema"
        sub1 = schema_dir / "sub1"
        sub2 = schema_dir / "sub2"
        sub1.mkdir(parents=True)
        sub2.mkdir(parents=True)
        (sub1 / "Dup.yml").write_text("name: Dup1\n")
        (sub2 / "Dup.yml").write_text("name: Dup2\n")
        with pytest.raises(FileNotFoundError, match="Multiple"):
            SchemaLoader.load_schema("Dup", schema_dir=schema_dir)


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

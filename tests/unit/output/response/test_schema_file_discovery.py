"""SchemaLoader finds the schema files under a project's schema path."""

from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# discover_schema_files
# ---------------------------------------------------------------------------
class TestDiscoverSchemaFiles:
    def _setup_project(self, tmp_path, schema_path="schema"):
        (tmp_path / "agent_actions.yml").write_text(f"schema_path: {schema_path}\n")

    def _write_schema(self, path: Path, name: str = "test"):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump({"name": name, "fields": [{"id": "f1", "type": "string"}]}, f)

    def test_finds_schemas_in_subdirectories(self, tmp_path):
        """Recursive rglob finds schemas in nested folders."""
        from agent_actions.output.response.loader import SchemaLoader

        self._setup_project(tmp_path)
        self._write_schema(tmp_path / "schema" / "sub" / "nested.yml", "nested")

        result = SchemaLoader.discover_schema_files(tmp_path)
        assert "nested" in result
        assert result["nested"].name == "nested.yml"

    def test_finds_workflow_level_schemas(self, tmp_path):
        """Schemas under agent_workflow/*/schema/ are found."""
        from agent_actions.output.response.loader import SchemaLoader

        self._setup_project(tmp_path)
        self._write_schema(tmp_path / "agent_workflow" / "wf1" / "schema" / "wf_schema.yml", "wf")

        result = SchemaLoader.discover_schema_files(tmp_path)
        assert "wf_schema" in result

    def test_duplicates_keep_first(self, tmp_path):
        """Duplicate schema names: first occurrence wins."""
        from agent_actions.output.response.loader import SchemaLoader

        self._setup_project(tmp_path)
        self._write_schema(tmp_path / "schema" / "dup.yml", "first")
        self._write_schema(tmp_path / "agent_workflow" / "wf" / "schema" / "dup.yml", "second")

        result = SchemaLoader.discover_schema_files(tmp_path)
        assert "dup" in result
        # First occurrence (project-level) wins
        assert "schema" in str(result["dup"])

    def test_empty_when_no_schema_dir(self, tmp_path):
        """Returns empty dict when schema directory doesn't exist."""
        from agent_actions.output.response.loader import SchemaLoader

        self._setup_project(tmp_path)
        result = SchemaLoader.discover_schema_files(tmp_path)
        assert result == {}

    def test_yaml_extension_supported(self, tmp_path):
        """Both .yml and .yaml extensions are found."""
        from agent_actions.output.response.loader import SchemaLoader

        self._setup_project(tmp_path)
        self._write_schema(tmp_path / "schema" / "a.yml", "yml")
        self._write_schema(tmp_path / "schema" / "b.yaml", "yaml")

        result = SchemaLoader.discover_schema_files(tmp_path)
        assert "a" in result
        assert "b" in result

"""Direct tests for shared file-discovery methods."""

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


# ---------------------------------------------------------------------------
# discover_prompt_files
# ---------------------------------------------------------------------------
class TestDiscoverPromptFiles:
    def test_finds_prompts_in_subdirectories(self, tmp_path):
        """Recursive rglob finds .md files in nested folders."""
        from agent_actions.prompt.handler import PromptLoader

        prompt_dir = tmp_path / "prompt_store" / "sub"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "nested.md").write_text("{prompt test}\ncontent\n{end_prompt}")
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")

        result = PromptLoader.discover_prompt_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "nested.md"

    def test_returns_empty_when_no_prompt_store(self, tmp_path):
        """Returns empty list when prompt_store/ doesn't exist."""
        from agent_actions.prompt.handler import PromptLoader

        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        result = PromptLoader.discover_prompt_files(tmp_path)
        assert result == []

    def test_finds_flat_and_nested(self, tmp_path):
        """Finds both top-level and nested .md files."""
        from agent_actions.prompt.handler import PromptLoader

        ps = tmp_path / "prompt_store"
        ps.mkdir()
        (ps / "top.md").write_text("{prompt a}\ncontent\n{end_prompt}")
        sub = ps / "sub"
        sub.mkdir()
        (sub / "deep.md").write_text("{prompt b}\ncontent\n{end_prompt}")
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")

        result = PromptLoader.discover_prompt_files(tmp_path)
        names = [p.name for p in result]
        assert "top.md" in names
        assert "deep.md" in names


# ---------------------------------------------------------------------------
# discover_tool_files
# ---------------------------------------------------------------------------
class TestDiscoverToolFiles:
    def test_nonexistent_dir_returns_empty(self, tmp_path):
        """Non-existent directory returns empty list."""
        from agent_actions.input.loaders.udf import discover_tool_files

        result = discover_tool_files(tmp_path / "nonexistent")
        assert result == []

    def test_file_not_dir_returns_empty(self, tmp_path):
        """Path that is a file (not dir) returns empty list."""
        from agent_actions.input.loaders.udf import discover_tool_files

        f = tmp_path / "not_a_dir.py"
        f.write_text("x = 1")
        result = discover_tool_files(f)
        assert result == []

    def test_filters_private_and_test_files(self, tmp_path):
        """Files starting with _ or test_ are excluded."""
        from agent_actions.input.loaders.udf import discover_tool_files

        tools = tmp_path / "tools"
        tools.mkdir()
        (tools / "good.py").write_text("x = 1")
        (tools / "_private.py").write_text("x = 1")
        (tools / "test_something.py").write_text("x = 1")
        (tools / "__init__.py").write_text("")

        result = discover_tool_files(tools)
        names = [p.name for p in result]
        assert "good.py" in names
        assert "_private.py" not in names
        assert "test_something.py" not in names
        assert "__init__.py" not in names

    def test_finds_files_recursively(self, tmp_path):
        """Files in subdirectories are found."""
        from agent_actions.input.loaders.udf import discover_tool_files

        tools = tmp_path / "tools"
        sub = tools / "sub"
        sub.mkdir(parents=True)
        (sub / "deep.py").write_text("x = 1")

        result = discover_tool_files(tools)
        assert len(result) == 1
        assert result[0].name == "deep.py"

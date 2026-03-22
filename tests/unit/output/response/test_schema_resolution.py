"""Tests for multi-level schema resolution in SchemaLoader.load_schema()."""

import pytest
import yaml

from agent_actions.config.path_config import get_schema_path
from agent_actions.errors import ConfigValidationError
from agent_actions.output.response.loader import SchemaLoader


def _setup_project(tmp_path, schema_path="schema"):
    """Create agent_actions.yml with schema_path configured."""
    (tmp_path / "agent_actions.yml").write_text(f"schema_path: {schema_path}\n")


def _write_schema(path, name, fields=None):
    """Write a minimal schema YAML file with a distinguishable name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {"name": name, "fields": fields or [{"id": "f1", "type": "string"}]}
    with open(path, "w") as f:
        yaml.dump(content, f)


class TestMultiLevelResolution:
    """Tests for the 3-step resolution order."""

    def test_step1_project_level_found(self, tmp_path):
        """Schema in project-level schema/ dir is found."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "schema" / "my_schema.yml", "project_level")
        result = SchemaLoader.load_schema("my_schema", project_root=tmp_path)
        assert result["name"] == "project_level"

    def test_step1_project_level_subdirectory(self, tmp_path):
        """Schema in project-level schema/sub/ dir is found via rglob."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "schema" / "workflow_a" / "nested.yml", "nested_in_project")
        result = SchemaLoader.load_schema("nested", project_root=tmp_path)
        assert result["name"] == "nested_in_project"

    def test_step2_workflow_level_found(self, tmp_path):
        """Schema in a workflow's schema dir is found."""
        _setup_project(tmp_path)
        _write_schema(
            tmp_path / "agent_workflow" / "my_wf" / "schema" / "wf_schema.yml",
            "workflow_level",
        )
        result = SchemaLoader.load_schema("wf_schema", project_root=tmp_path)
        assert result["name"] == "workflow_level"

    def test_step3_search_all_workflows(self, tmp_path):
        """Schema in another workflow's schema dir is found without workflow_name."""
        _setup_project(tmp_path)
        _write_schema(
            tmp_path / "agent_workflow" / "other_wf" / "schema" / "other_schema.yml",
            "found_via_step3",
        )
        result = SchemaLoader.load_schema("other_schema", project_root=tmp_path)
        assert result["name"] == "found_via_step3"

    def test_workflow_level_found_without_explicit_name(self, tmp_path):
        """Schema in any workflow's schema dir is found via all-workflows search."""
        _setup_project(tmp_path)
        _write_schema(
            tmp_path / "agent_workflow" / "wf_a" / "schema" / "step3_only.yml",
            "step3_only",
        )
        result = SchemaLoader.load_schema("step3_only", project_root=tmp_path)
        assert result["name"] == "step3_only"

    def test_yaml_extension_supported(self, tmp_path):
        """Schema with .yaml extension is found."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "schema" / "yaml_ext.yaml", "yaml_extension")
        result = SchemaLoader.load_schema("yaml_ext", project_root=tmp_path)
        assert result["name"] == "yaml_extension"


class TestGlobalUniqueness:
    """Tests for duplicate name detection (warns, first occurrence wins)."""

    def test_same_name_in_two_locations_uses_first(self, tmp_path):
        """Same schema name in project-level and workflow-level: first wins."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "schema" / "dup.yml", "project_copy")
        _write_schema(tmp_path / "agent_workflow" / "wf" / "schema" / "dup.yml", "wf_copy")
        result = SchemaLoader.load_schema("dup", project_root=tmp_path)
        assert result["name"] == "project_copy"  # first occurrence wins

    def test_same_name_in_two_workflows_uses_first(self, tmp_path):
        """Same schema name in two different workflow dirs: first alphabetically wins."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "agent_workflow" / "wf_a" / "schema" / "dup.yml", "wf_a_copy")
        _write_schema(tmp_path / "agent_workflow" / "wf_b" / "schema" / "dup.yml", "wf_b_copy")
        result = SchemaLoader.load_schema("dup", project_root=tmp_path)
        assert result["name"] == "wf_a_copy"  # first alphabetically

    def test_yml_and_yaml_same_name_uses_first(self, tmp_path):
        """Same schema name with .yml and .yaml extensions: first found wins."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "schema" / "both.yml", "yml_version")
        _write_schema(tmp_path / "schema" / "both.yaml", "yaml_version")
        result = SchemaLoader.load_schema("both", project_root=tmp_path)
        assert result["name"] in ("yml_version", "yaml_version")

    def test_not_found_raises(self, tmp_path):
        """Schema not found anywhere raises FileNotFoundError."""
        _setup_project(tmp_path)
        (tmp_path / "schema").mkdir()
        with pytest.raises(FileNotFoundError, match="not found"):
            SchemaLoader.load_schema("missing", project_root=tmp_path)


class TestSchemaPathConfig:
    """Tests for custom schema_path from config."""

    def test_custom_schema_path(self, tmp_path):
        """Custom schema_path is respected."""
        _setup_project(tmp_path, schema_path="schemas")
        _write_schema(tmp_path / "schemas" / "my_schema.yml", "custom_dir")
        result = SchemaLoader.load_schema("my_schema", project_root=tmp_path)
        assert result["name"] == "custom_dir"

    def test_custom_schema_path_workflow_level(self, tmp_path):
        """Custom schema_path is respected at workflow level too."""
        _setup_project(tmp_path, schema_path="defs")
        _write_schema(
            tmp_path / "agent_workflow" / "wf" / "defs" / "my_schema.yml",
            "custom_wf_dir",
        )
        result = SchemaLoader.load_schema("my_schema", project_root=tmp_path)
        assert result["name"] == "custom_wf_dir"

    def test_missing_schema_path_config_raises(self, tmp_path):
        """No agent_actions.yml raises ConfigValidationError."""
        with pytest.raises(ConfigValidationError, match="schema_path"):
            get_schema_path(tmp_path)

    def test_missing_schema_path_key_raises(self, tmp_path):
        """Config without schema_path key raises ConfigValidationError."""
        (tmp_path / "agent_actions.yml").write_text("tool_path: ['tools']\n")
        with pytest.raises(ConfigValidationError, match="schema_path"):
            get_schema_path(tmp_path)

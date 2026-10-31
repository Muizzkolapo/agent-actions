"""Tests for multi-level schema resolution in SchemaLoader.load_schema()."""

import pytest
import yaml

from agent_actions.config.path_config import get_schema_path
from agent_actions.errors import ConfigValidationError, SchemaValidationError
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

    @pytest.mark.parametrize(
        ("relpath", "ref"),
        [
            pytest.param("schema/my_schema.yml", "my_schema", id="step1-project-level"),
            pytest.param(
                "schema/workflow_a/nested.yml", "nested", id="step1-project-level-subdirectory"
            ),
            pytest.param(
                "agent_workflow/my_wf/schema/wf_schema.yml", "wf_schema", id="step2-workflow-level"
            ),
            pytest.param(
                "agent_workflow/other_wf/schema/other_schema.yml",
                "other_schema",
                id="step3-search-all-workflows",
            ),
            pytest.param(
                "agent_workflow/wf_a/schema/step3_only.yml",
                "step3_only",
                id="workflow-level-without-explicit-name",
            ),
            pytest.param("schema/yaml_ext.yaml", "yaml_ext", id="yaml-extension"),
        ],
    )
    def test_schema_is_found(self, tmp_path, relpath, ref):
        _setup_project(tmp_path)
        _write_schema(tmp_path / relpath, f"found_{ref}")
        result = SchemaLoader.load_schema(ref, project_root=tmp_path)
        assert result["name"] == f"found_{ref}"


class TestGlobalUniqueness:
    """Tests for duplicate name detection (ambiguous references hard-fail)."""

    def test_same_name_in_two_locations_raises(self, tmp_path):
        """Same schema name in project-level and workflow-level is ambiguous."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "schema" / "dup.yml", "project_copy")
        _write_schema(tmp_path / "agent_workflow" / "wf" / "schema" / "dup.yml", "wf_copy")
        with pytest.raises(SchemaValidationError, match="ambiguous"):
            SchemaLoader.load_schema("dup", project_root=tmp_path)

    def test_same_name_in_two_workflows_raises(self, tmp_path):
        """Same schema name in two different workflow dirs is ambiguous."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "agent_workflow" / "wf_a" / "schema" / "dup.yml", "wf_a_copy")
        _write_schema(tmp_path / "agent_workflow" / "wf_b" / "schema" / "dup.yml", "wf_b_copy")
        with pytest.raises(SchemaValidationError, match="ambiguous"):
            SchemaLoader.load_schema("dup", project_root=tmp_path)

    def test_yml_and_yaml_same_name_raises(self, tmp_path):
        """Same schema name with .yml and .yaml extensions is ambiguous."""
        _setup_project(tmp_path)
        _write_schema(tmp_path / "schema" / "both.yml", "yml_version")
        _write_schema(tmp_path / "schema" / "both.yaml", "yaml_version")
        with pytest.raises(SchemaValidationError, match="ambiguous"):
            SchemaLoader.load_schema("both", project_root=tmp_path)

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

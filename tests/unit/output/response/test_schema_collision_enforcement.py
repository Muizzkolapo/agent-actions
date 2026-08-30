"""Ambiguous schema references hard-fail instead of resolving alphabetically.

Discovery stays lenient — the LSP indexer and docs scanner call it directly —
but ``load_schema`` raises ``SchemaValidationError`` naming every colliding
path when the requested stem is ambiguous. Collisions among unreferenced
names warn once per process, not once per filesystem walk.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from agent_actions.errors import SchemaValidationError
from agent_actions.output.response import loader as loader_module
from agent_actions.output.response.loader import SchemaLoader


def _setup_project(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")


def _write_schema(path, name):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump({"name": name, "fields": [{"id": "f1", "type": "string"}]}, f)


def test_ambiguous_reference_raises_naming_all_paths(tmp_path):
    _setup_project(tmp_path)
    path_a = tmp_path / "agent_workflow" / "wf_a" / "schema" / "answer.yml"
    path_b = tmp_path / "agent_workflow" / "wf_b" / "schema" / "answer.yml"
    _write_schema(path_a, "wf_a_copy")
    _write_schema(path_b, "wf_b_copy")
    with pytest.raises(SchemaValidationError) as exc_info:
        SchemaLoader.load_schema("answer", project_root=tmp_path)
    message = str(exc_info.value)
    assert str(path_a) in message, f"error must name {path_a}, got: {message}"
    assert str(path_b) in message, f"error must name {path_b}, got: {message}"


def test_project_level_collision_with_workflow_raises(tmp_path):
    _setup_project(tmp_path)
    _write_schema(tmp_path / "schema" / "dup.yml", "project_copy")
    _write_schema(tmp_path / "agent_workflow" / "wf" / "schema" / "dup.yml", "wf_copy")
    with pytest.raises(SchemaValidationError):
        SchemaLoader.load_schema("dup", project_root=tmp_path)


def test_same_dir_extension_collision_raises(tmp_path):
    _setup_project(tmp_path)
    _write_schema(tmp_path / "schema" / "dup.yml", "yml_copy")
    (tmp_path / "schema" / "dup.json").write_text('{"name": "json_copy", "fields": []}')
    with pytest.raises(SchemaValidationError):
        SchemaLoader.load_schema("dup", project_root=tmp_path)


def test_unreferenced_collision_does_not_block_unique_name(tmp_path):
    """A collision between names nothing references must not fail unrelated loads."""
    _setup_project(tmp_path)
    _write_schema(tmp_path / "agent_workflow" / "wf_a" / "schema" / "dup.yml", "a")
    _write_schema(tmp_path / "agent_workflow" / "wf_b" / "schema" / "dup.yml", "b")
    _write_schema(tmp_path / "schema" / "unique.yml", "unique_schema")
    result = SchemaLoader.load_schema("unique", project_root=tmp_path)
    assert result["name"] == "unique_schema"


def test_missing_name_still_raises_file_not_found(tmp_path):
    """Ambiguity enforcement must not change the not-found contract."""
    _setup_project(tmp_path)
    (tmp_path / "schema").mkdir()
    with pytest.raises(FileNotFoundError, match="not found"):
        SchemaLoader.load_schema("nonexistent", project_root=tmp_path)


def test_collision_warning_fires_once_for_repeated_discovery(tmp_path):
    """The walk used to re-warn on every call — once per action in an inspect run."""
    _setup_project(tmp_path)
    _write_schema(tmp_path / "agent_workflow" / "wf_a" / "schema" / "dup.yml", "a")
    _write_schema(tmp_path / "agent_workflow" / "wf_b" / "schema" / "dup.yml", "b")
    with patch.object(loader_module.logger, "warning") as warn:
        SchemaLoader.discover_schema_files(tmp_path)
        SchemaLoader.discover_schema_files(tmp_path)
    dup_warnings = [c for c in warn.call_args_list if "dup" in str(c)]
    assert len(dup_warnings) == 1, (
        f"collision warning must fire once per process, fired {len(dup_warnings)}x"
    )


def test_discovery_returns_all_non_colliding_schemas_despite_collision(tmp_path):
    """Discovery itself must stay lenient — direct callers (LSP, docs) never crash."""
    _setup_project(tmp_path)
    _write_schema(tmp_path / "agent_workflow" / "wf_a" / "schema" / "dup.yml", "a")
    _write_schema(tmp_path / "agent_workflow" / "wf_b" / "schema" / "dup.yml", "b")
    _write_schema(tmp_path / "schema" / "unique.yml", "u")
    result = SchemaLoader.discover_schema_files(tmp_path)
    assert "unique" in result
    assert "dup" in result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

"""Tests for change_tracker module."""

import json
from pathlib import Path

from agent_actions.tooling.docs.change_tracker import (
    collect_resource_mtimes,
    compute_changes,
    load_previous_mtimes,
)


class TestCollectResourceMtimes:
    def test_collects_workflow_mtimes(self, tmp_path: Path):
        wf_file = tmp_path / "my_wf.yml"
        wf_file.write_text("name: my_wf")

        workflows = {"my_wf": {"rendered": str(wf_file), "original": None}}
        result = collect_resource_mtimes(workflows, {}, {}, {})
        assert "my_wf" in result["workflows"]
        assert isinstance(result["workflows"]["my_wf"], float)

    def test_falls_back_to_original_path(self, tmp_path: Path):
        wf_file = tmp_path / "original.yml"
        wf_file.write_text("name: wf")

        workflows = {"wf": {"rendered": None, "original": str(wf_file)}}
        result = collect_resource_mtimes(workflows, {}, {}, {})
        assert "wf" in result["workflows"]

    def test_collects_prompt_mtimes(self, tmp_path: Path):
        prompt_file = tmp_path / "prompts.md"
        prompt_file.write_text("{prompt test}content{end_prompt}")

        prompts = {"test": {"source_file": str(prompt_file)}}
        result = collect_resource_mtimes({}, prompts, {}, {})
        assert "test" in result["prompts"]

    def test_collects_schema_mtimes(self, tmp_path: Path):
        schema_file = tmp_path / "schema.yml"
        schema_file.write_text("fields: []")

        schemas = {"my_schema": {"source_file": str(schema_file)}}
        result = collect_resource_mtimes({}, {}, schemas, {})
        assert "my_schema" in result["schemas"]

    def test_collects_tool_mtimes_absolute(self, tmp_path: Path):
        tool_file = tmp_path / "tool.py"
        tool_file.write_text("def run(): pass")

        tools = {"run": {"file_path": str(tool_file)}}
        result = collect_resource_mtimes({}, {}, {}, tools)
        assert "run" in result["tools"]

    def test_collects_tool_mtimes_relative_with_project_root(self, tmp_path: Path):
        tool_file = tmp_path / "tools" / "lookup.py"
        tool_file.parent.mkdir()
        tool_file.write_text("def lookup(): pass")

        tools = {"lookup": {"file_path": "tools/lookup.py"}}
        result = collect_resource_mtimes({}, {}, {}, tools, project_root=tmp_path)
        assert "lookup" in result["tools"]

    def test_relative_tool_path_without_project_root_may_miss(self):
        tools = {"missing": {"file_path": "tools/nonexistent.py"}}
        result = collect_resource_mtimes({}, {}, {}, tools)
        assert "missing" not in result["tools"]

    def test_missing_file_omitted(self):
        prompts = {"ghost": {"source_file": "/nonexistent/file.md"}}
        result = collect_resource_mtimes({}, prompts, {}, {})
        assert "ghost" not in result["prompts"]

    def test_empty_inputs(self):
        result = collect_resource_mtimes({}, {}, {}, {})
        assert result == {"workflows": {}, "prompts": {}, "schemas": {}, "tools": {}}

    def test_none_inputs(self):
        result = collect_resource_mtimes(None, None, None, None)
        assert result == {"workflows": {}, "prompts": {}, "schemas": {}, "tools": {}}


class TestComputeChanges:
    def test_all_added_on_first_run(self):
        current = {
            "workflows": {"a": 1.0, "b": 2.0},
            "prompts": {},
            "schemas": {},
            "tools": {},
        }
        result = compute_changes(current, {}, None)
        assert result["is_first_run"] is True
        assert result["workflows"]["added"] == ["a", "b"]
        assert result["summary"]["total_added"] == 2

    def test_modified_detected(self):
        current = {"workflows": {"a": 2.0}, "prompts": {}, "schemas": {}, "tools": {}}
        previous = {"workflows": {"a": 1.0}}
        result = compute_changes(current, previous, "2026-04-07T00:00:00")
        assert result["workflows"]["modified"] == ["a"]
        assert result["summary"]["total_modified"] == 1
        assert result["is_first_run"] is False

    def test_removed_detected(self):
        current = {"workflows": {}, "prompts": {}, "schemas": {}, "tools": {}}
        previous = {"workflows": {"old": 1.0}}
        result = compute_changes(current, previous, "2026-04-07T00:00:00")
        assert result["workflows"]["removed"] == ["old"]
        assert result["summary"]["total_removed"] == 1

    def test_unchanged_not_reported(self):
        current = {"workflows": {"a": 1.0}, "prompts": {}, "schemas": {}, "tools": {}}
        previous = {"workflows": {"a": 1.0}}
        result = compute_changes(current, previous, "2026-04-07T00:00:00")
        assert result["workflows"] == {"added": [], "modified": [], "removed": []}
        assert result["summary"] == {
            "total_added": 0,
            "total_modified": 0,
            "total_removed": 0,
        }

    def test_mixed_changes_across_categories(self):
        current = {
            "workflows": {"a": 2.0, "c": 3.0},
            "prompts": {"p1": 1.0},
            "schemas": {"s_new": 1.0},
            "tools": {},
        }
        previous = {
            "workflows": {"a": 1.0, "b": 1.0},
            "prompts": {"p1": 1.0},
            "schemas": {},
            "tools": {"old_tool": 1.0},
        }
        result = compute_changes(current, previous, "2026-04-07T00:00:00")
        assert result["workflows"]["added"] == ["c"]
        assert result["workflows"]["modified"] == ["a"]
        assert result["workflows"]["removed"] == ["b"]
        assert result["prompts"] == {"added": [], "modified": [], "removed": []}
        assert result["schemas"]["added"] == ["s_new"]
        assert result["tools"]["removed"] == ["old_tool"]
        assert result["summary"]["total_added"] == 2
        assert result["summary"]["total_modified"] == 1
        assert result["summary"]["total_removed"] == 2

    def test_results_sorted(self):
        current = {
            "workflows": {"z": 1.0, "a": 1.0, "m": 1.0},
            "prompts": {},
            "schemas": {},
            "tools": {},
        }
        result = compute_changes(current, {}, None)
        assert result["workflows"]["added"] == ["a", "m", "z"]

    def test_previous_generated_at_preserved(self):
        current = {"workflows": {}, "prompts": {}, "schemas": {}, "tools": {}}
        result = compute_changes(current, {"workflows": {}}, "2026-04-07T18:30:00")
        assert result["previous_generated_at"] == "2026-04-07T18:30:00"


class TestLoadPreviousMtimes:
    def test_no_file(self, tmp_path: Path):
        mtimes, gen_at = load_previous_mtimes(tmp_path / "nonexistent.json")
        assert mtimes == {}
        assert gen_at is None

    def test_valid_catalog(self, tmp_path: Path):
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "metadata": {"generated_at": "2026-04-07T00:00:00"},
                    "resource_mtimes": {"workflows": {"wf1": 100.0}},
                }
            )
        )
        mtimes, gen_at = load_previous_mtimes(catalog_path)
        assert mtimes["workflows"]["wf1"] == 100.0
        assert gen_at == "2026-04-07T00:00:00"

    def test_catalog_without_mtimes(self, tmp_path: Path):
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps({"metadata": {"generated_at": "2026-04-07T00:00:00"}}))
        mtimes, gen_at = load_previous_mtimes(catalog_path)
        assert mtimes == {}
        assert gen_at == "2026-04-07T00:00:00"

    def test_corrupt_json(self, tmp_path: Path):
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text("not json")
        mtimes, gen_at = load_previous_mtimes(catalog_path)
        assert mtimes == {}
        assert gen_at is None

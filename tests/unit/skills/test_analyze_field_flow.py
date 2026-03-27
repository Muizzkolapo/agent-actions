"""Regression tests for analyze_field_flow.load_node_data — B-7: JSON guard."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_PATH = (
    Path(__file__).parents[3]
    / "agent_actions"
    / "skills"
    / "agent-actions-workflow"
    / "scripts"
    / "analyze_field_flow.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("analyze_field_flow", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if not _SCRIPT_PATH.exists():
    pytest.skip(f"Script not found: {_SCRIPT_PATH}", allow_module_level=True)

_mod = _load_module()
load_node_data = _mod.load_node_data


class TestLoadNodeDataJsonGuard:
    """load_node_data must return {} and not raise on bad JSON or non-dict array items."""

    def test_invalid_json_returns_empty_dict(self, tmp_path):
        node_dir = tmp_path / "node_1_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text("{not valid json!!}")

        result = load_node_data(node_dir)
        assert result == {}

    def test_non_dict_in_json_array_returns_empty_dict(self, tmp_path):
        node_dir = tmp_path / "node_2_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text(json.dumps([42]))

        result = load_node_data(node_dir)
        assert result == {}

    def test_string_in_json_array_returns_empty_dict(self, tmp_path):
        node_dir = tmp_path / "node_3_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text(json.dumps(["hello"]))

        result = load_node_data(node_dir)
        assert result == {}

    def test_valid_dict_in_array_returns_fields(self, tmp_path):
        node_dir = tmp_path / "node_4_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text(json.dumps([{"name": "Alice", "age": 30}]))

        result = load_node_data(node_dir)
        assert "name" in result
        assert "age" in result

    def test_empty_directory_returns_none(self, tmp_path):
        node_dir = tmp_path / "node_5_action"
        node_dir.mkdir()

        result = load_node_data(node_dir)
        assert result is None

    def test_valid_plain_dict_returns_fields(self, tmp_path):
        node_dir = tmp_path / "node_6_action"
        node_dir.mkdir()
        (node_dir / "out.json").write_text(json.dumps({"score": 0.9, "label": "positive"}))

        result = load_node_data(node_dir)
        assert "score" in result
        assert "label" in result

    def test_json_null_returns_empty_dict(self, tmp_path):
        node_dir = tmp_path / "node_7_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text("null")

        result = load_node_data(node_dir)
        assert result == {}

    def test_empty_json_array_returns_empty_dict(self, tmp_path):
        node_dir = tmp_path / "node_8_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text("[]")

        result = load_node_data(node_dir)
        assert result == {}

    def test_os_error_returns_empty_dict(self, tmp_path):
        node_dir = tmp_path / "node_9_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text("{}")  # file exists so glob finds it

        with patch("builtins.open", side_effect=PermissionError("permission denied")):
            result = load_node_data(node_dir)
        assert result == {}

    def test_bare_scalar_returns_empty_dict(self, tmp_path):
        # JSON number at top level — not a dict or list, must not crash extract_fields
        node_dir = tmp_path / "node_10_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text("42")

        result = load_node_data(node_dir)
        assert result == {}

    def test_bare_string_returns_empty_dict(self, tmp_path):
        node_dir = tmp_path / "node_11_action"
        node_dir.mkdir()
        (node_dir / "combined_out.json").write_text('"hello"')

        result = load_node_data(node_dir)
        assert result == {}

"""Tests for load_structured_file utility."""

import json

import pytest
import yaml

from agent_actions.utils.file_utils import load_structured_file


class TestLoadStructuredFile:
    """Tests for extension-aware file loading."""

    def test_loads_json(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}))
        assert load_structured_file(f) == {"key": "value"}

    def test_loads_yml(self, tmp_path):
        f = tmp_path / "data.yml"
        f.write_text(yaml.dump({"key": "value"}))
        assert load_structured_file(f) == {"key": "value"}

    def test_loads_yaml(self, tmp_path):
        f = tmp_path / "data.yaml"
        f.write_text(yaml.dump({"key": "value"}))
        assert load_structured_file(f) == {"key": "value"}

    def test_malformed_json_raises_json_error(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json!!}")
        with pytest.raises(json.JSONDecodeError):
            load_structured_file(f)

    def test_malformed_yaml_raises_yaml_error(self, tmp_path):
        f = tmp_path / "bad.yml"
        f.write_text(":\n  :\n    - ][")
        with pytest.raises(yaml.YAMLError):
            load_structured_file(f)

    def test_non_yaml_extension_parsed_as_yaml(self, tmp_path):
        """Any non-.json extension falls through to YAML parsing."""
        f = tmp_path / "data.txt"
        f.write_text("key: value\n")
        assert load_structured_file(f) == {"key": "value"}

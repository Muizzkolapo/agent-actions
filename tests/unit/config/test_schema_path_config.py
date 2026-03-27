"""Tests for get_schema_path configuration helper."""

import pytest
import yaml

from agent_actions.config.path_config import get_schema_path
from agent_actions.errors import ConfigValidationError


class TestGetSchemaPath:
    """Tests for get_schema_path() — required project config key."""

    def test_raises_when_no_config(self, tmp_path):
        """No agent_actions.yml → raises ConfigValidationError."""
        with pytest.raises(ConfigValidationError, match="schema_path"):
            get_schema_path(tmp_path)

    def test_raises_when_key_absent(self, tmp_path):
        """Config exists but has no schema_path key → raises."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"tool_path": ["tools"]}))
        with pytest.raises(ConfigValidationError, match="schema_path"):
            get_schema_path(tmp_path)

    def test_returns_configured_value(self, tmp_path):
        """Config has schema_path → returns that value."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"schema_path": "custom_schemas"}))
        assert get_schema_path(tmp_path) == "custom_schemas"

    def test_raises_on_empty_config(self, tmp_path):
        """Empty YAML file → raises (no schema_path key)."""
        (tmp_path / "agent_actions.yml").write_text("")
        with pytest.raises(ConfigValidationError, match="No agent_actions.yml"):
            get_schema_path(tmp_path)

    def test_standard_schema_value(self, tmp_path):
        """Standard schema_path: schema works."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"schema_path": "schema"}))
        assert get_schema_path(tmp_path) == "schema"

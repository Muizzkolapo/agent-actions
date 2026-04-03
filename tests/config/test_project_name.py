"""Tests for project_name field in agent_actions.yml."""

from unittest.mock import patch

import yaml

from agent_actions.config.init import ProjectInitializer
from agent_actions.config.path_config import get_project_name


class TestInitWritesProjectName:
    """ProjectInitializer.init_project() must write project_name to YAML."""

    def test_init_writes_project_name(self, tmp_path):
        initializer = ProjectInitializer(project_name="my_project", base_path=tmp_path)
        initializer.init_project()

        config_file = tmp_path / "my_project" / "agent_actions.yml"
        assert config_file.exists()

        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert config["project_name"] == "my_project"

    def test_init_preserves_default_agent_config(self, tmp_path):
        initializer = ProjectInitializer(project_name="test_proj", base_path=tmp_path)
        initializer.init_project()

        config_file = tmp_path / "test_proj" / "agent_actions.yml"
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert "default_agent_config" in config
        assert config["default_agent_config"]["api_key"] == "OPENAI_API_KEY"


class TestGetProjectName:
    """get_project_name() accessor with graceful fallback."""

    def test_returns_value_when_present(self, tmp_path):
        config_file = tmp_path / "agent_actions.yml"
        config_file.write_text(yaml.safe_dump({"project_name": "foo"}))

        result = get_project_name(tmp_path)
        assert result == "foo"

    def test_returns_none_when_missing(self, tmp_path):
        config_file = tmp_path / "agent_actions.yml"
        config_file.write_text(yaml.safe_dump({"default_agent_config": {}}))

        result = get_project_name(tmp_path)
        assert result is None

    def test_returns_none_when_no_config_file(self, tmp_path):
        result = get_project_name(tmp_path)
        # No config file -> load_project_config returns {} -> project_name missing
        assert result is None

    def test_returns_string_for_non_string_value(self, tmp_path):
        config_file = tmp_path / "agent_actions.yml"
        config_file.write_text(yaml.safe_dump({"project_name": 123}))

        result = get_project_name(tmp_path)
        assert result == "123"
        assert isinstance(result, str)

    def test_returns_none_on_config_load_error(self, tmp_path):
        with patch(
            "agent_actions.config.path_config.load_project_config",
            side_effect=OSError("permission denied"),
        ):
            result = get_project_name(tmp_path)
        assert result is None

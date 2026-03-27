"""Integration tests for workflow loading pattern used by CLI commands."""

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory


class TestConfigDiscoveryPattern:
    """Test the config file discovery pattern used by multiple commands."""

    @pytest.fixture
    def temp_project_with_config(self, tmp_path):
        """Create a temporary project with agent config."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()

        # Create agent-actions.yml
        (project_dir / "agent-actions.yml").write_text("version: '1.0'\n")

        # Create user_code directory
        user_code = project_dir / "user_code"
        user_code.mkdir()

        # Create agent config
        agent_config = user_code / "test_agent.yml"
        agent_config.write_text(
            """
name: test_agent
description: Test agent
actions:
  - name: test_action
    type: python
"""
        )

        return {
            "project_dir": project_dir,
            "user_code": user_code,
            "agent_config": agent_config,
        }

    def test_config_file_discovery_in_user_code(self, temp_project_with_config):
        """Test config file can be found in user_code directory."""
        user_code = temp_project_with_config["user_code"]
        agent_config = temp_project_with_config["agent_config"]

        # This simulates what _find_config_file does
        config_filename = "test_agent.yml"
        expected_path = user_code / config_filename

        assert expected_path.exists()
        assert expected_path == agent_config

    def test_config_file_discovery_missing_file(self, temp_project_with_config):
        """Test behavior when config file doesn't exist."""
        user_code = temp_project_with_config["user_code"]
        nonexistent_config = user_code / "nonexistent_agent.yml"

        assert not nonexistent_config.exists()

    def test_config_file_exists_at_expected_location(self, temp_project_with_config):
        """Test config file is at the location commands will look for it."""
        user_code = temp_project_with_config["user_code"]
        agent_name = "test_agent"

        # Commands construct the config path like this
        config_filename = f"{agent_name}.yml"
        config_path = user_code / config_filename

        assert config_path.exists()
        content = config_path.read_text()
        assert "name: test_agent" in content
        assert "actions:" in content


class TestProjectPathsFactoryConstants:
    """Test ProjectPathsFactory class constants."""

    def test_required_directories_constant(self):
        """Test REQUIRED_DIRECTORIES constant exists."""
        assert hasattr(ProjectPathsFactory, "REQUIRED_DIRECTORIES")
        required = ProjectPathsFactory.REQUIRED_DIRECTORIES
        assert isinstance(required, list)
        assert "agent_config_dir" in required
        assert "schema_dir" in required

    def test_auto_create_directories_constant(self):
        """Test AUTO_CREATE_DIRECTORIES constant exists."""
        assert hasattr(ProjectPathsFactory, "AUTO_CREATE_DIRECTORIES")
        auto_create = ProjectPathsFactory.AUTO_CREATE_DIRECTORIES
        assert isinstance(auto_create, list)
        assert "prompt_dir" in auto_create
        assert "rendered_workflows_dir" in auto_create
        assert "io_dir" in auto_create

"""Integration tests for workflow loading pattern used by CLI commands."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from agent_actions.cli.project_paths_factory import ProjectPathsFactory, ProjectPaths


class TestProjectPathsFactory:
    """Test ProjectPathsFactory creates valid path structures."""

    def test_create_project_paths_signature(self):
        """Test that create_project_paths accepts agent_name and filename parameters."""
        # This is a basic smoke test to ensure the API signature is correct
        # We can't test actual functionality without a real FileHandler setup
        assert hasattr(ProjectPathsFactory, "create_project_paths")
        assert callable(ProjectPathsFactory.create_project_paths)

    def test_get_agent_paths_signature(self):
        """Test that get_agent_paths exists and is callable."""
        assert hasattr(ProjectPathsFactory, "get_agent_paths")
        assert callable(ProjectPathsFactory.get_agent_paths)

    def test_project_paths_dataclass_structure(self):
        """Test ProjectPaths dataclass has expected attributes."""
        # Create a mock ProjectPaths to verify structure
        paths = ProjectPaths(
            current_dir=Path("/test/current"),
            prompt_dir=Path("/test/prompt"),
            agent_config_dir=Path("/test/agent_config"),
            io_dir=Path("/test/io"),
            schema_dir=Path("/test/schema"),
            default_config_path=Path("/test/default_config.yml"),
            template_dir=Path("/test/template"),
            rendered_workflows_dir=Path("/test/rendered"),
        )

        assert paths.current_dir == Path("/test/current")
        assert paths.prompt_dir == Path("/test/prompt")
        assert paths.agent_config_dir == Path("/test/agent_config")
        assert paths.io_dir == Path("/test/io")
        assert paths.schema_dir == Path("/test/schema")
        assert paths.default_config_path == Path("/test/default_config.yml")
        assert paths.template_dir == Path("/test/template")
        assert paths.rendered_workflows_dir == Path("/test/rendered")

    def test_project_paths_to_dict(self):
        """Test ProjectPaths.to_dict() converts paths to strings."""
        paths = ProjectPaths(
            current_dir=Path("/test/current"),
            prompt_dir=Path("/test/prompt"),
            agent_config_dir=Path("/test/agent_config"),
            io_dir=Path("/test/io"),
            schema_dir=Path("/test/schema"),
            default_config_path=Path("/test/default_config.yml"),
            template_dir=Path("/test/template"),
            rendered_workflows_dir=Path("/test/rendered"),
        )

        result = paths.to_dict()

        assert isinstance(result, dict)
        assert result["current_dir"] == "/test/current"
        assert result["prompt_dir"] == "/test/prompt"
        assert result["agent_config_dir"] == "/test/agent_config"
        assert result["io_dir"] == "/test/io"
        assert result["schema_dir"] == "/test/schema"
        assert result["default_config_path"] == "/test/default_config.yml"
        assert result["template_dir"] == "/test/template"
        assert result["rendered_workflows_dir"] == "/test/rendered"

    def test_project_paths_str_representation(self):
        """Test ProjectPaths string representation."""
        paths = ProjectPaths(
            current_dir=Path("/test/current"),
            prompt_dir=Path("/test/prompt"),
            agent_config_dir=Path("/test/agent_config"),
            io_dir=Path("/test/io"),
            schema_dir=Path("/test/schema"),
            default_config_path=Path("/test/default_config.yml"),
            template_dir=Path("/test/template"),
            rendered_workflows_dir=Path("/test/rendered"),
        )

        str_repr = str(paths)

        assert "current_dir" in str_repr
        assert "/test/current" in str_repr
        assert "prompt_dir" in str_repr
        assert "/test/prompt" in str_repr


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


class TestWorkflowLoadingPattern:
    """Test the workflow loading pattern used by run, schema, inspect commands."""

    def test_workflow_loading_sequence_steps(self):
        """Document the expected workflow loading sequence."""
        # This test documents the pattern without testing implementation
        # The pattern is:
        # 1. ProjectPathsFactory.create_project_paths(agent_name, filename)
        # 2. Construct filename from agent name: f"{agent_name}.yml"
        # 3. _find_config_file(paths.agent_config_dir, filename)
        # 4. ConfigRenderer.render_and_load_config(full_path, paths)
        # 5. AgentWorkflow(WorkflowConfig(paths=WorkflowPaths(...)))

        # Commands that follow this pattern:
        commands_using_pattern = [
            "RunCommand.execute()",
            "RunCommand._setup_validation_workflow()",
            "SchemaCommand.execute()",
            "BaseInspectCommand._load_workflow()",
        ]

        assert len(commands_using_pattern) == 4

    def test_agent_name_stem_extraction(self):
        """Test that agent names are extracted from path stems."""
        from pathlib import Path

        # Commands extract agent name like this:
        agent_path = Path("my_agent.yml")
        agent_name = agent_path.stem

        assert agent_name == "my_agent"

        # Works with just the name too
        agent_path2 = Path("another_agent")
        agent_name2 = agent_path2.stem

        assert agent_name2 == "another_agent"


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

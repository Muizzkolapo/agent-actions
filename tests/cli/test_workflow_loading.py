"""Integration tests for workflow loading pattern used by CLI commands."""

from agent_actions.config.project_paths import ProjectPathsFactory


class TestProjectPathsFactoryConstants:
    """Test ProjectPathsFactory class constants."""

    def test_required_directories_constant(self):
        """Test REQUIRED_DIRECTORIES constant exists."""
        assert hasattr(ProjectPathsFactory, "REQUIRED_DIRECTORIES")
        required = ProjectPathsFactory.REQUIRED_DIRECTORIES
        assert isinstance(required, list)
        assert "agent_config_dir" in required
        # schema_dir is validated conditionally based on json_mode,
        # not unconditionally in REQUIRED_DIRECTORIES
        assert "schema_dir" not in required

    def test_auto_create_directories_constant(self):
        """Test AUTO_CREATE_DIRECTORIES constant exists."""
        assert hasattr(ProjectPathsFactory, "AUTO_CREATE_DIRECTORIES")
        auto_create = ProjectPathsFactory.AUTO_CREATE_DIRECTORIES
        assert isinstance(auto_create, list)
        assert "prompt_dir" in auto_create
        assert "rendered_workflows_dir" in auto_create
        assert "io_dir" in auto_create

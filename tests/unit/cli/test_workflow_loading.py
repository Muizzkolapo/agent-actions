"""Integration tests for workflow loading pattern used by CLI commands."""

from agent_actions.config.project_paths import ProjectPathsFactory


class TestProjectPathsFactoryConstants:
    """Test ProjectPathsFactory class constants."""

    def test_required_directories_constant(self):
        """REQUIRED_DIRECTORIES lists the always-required directories."""
        required = ProjectPathsFactory.REQUIRED_DIRECTORIES
        assert "agent_config_dir" in required
        # schema_dir is validated conditionally based on json_mode,
        # not unconditionally in REQUIRED_DIRECTORIES
        assert "schema_dir" not in required

    def test_auto_create_directories_constant(self):
        """AUTO_CREATE_DIRECTORIES lists the directories created on demand."""
        auto_create = ProjectPathsFactory.AUTO_CREATE_DIRECTORIES
        assert "prompt_dir" in auto_create
        assert "rendered_workflows_dir" in auto_create
        assert "io_dir" in auto_create

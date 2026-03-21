"""Wave 12 T2-4 regression: --create-dirs flag for render/compile commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.compile import RenderCommand, _execute_render
from agent_actions.validation.render_validator import RenderCommandArgs


class TestRenderCommandCreateDirs:
    """T2-4: RenderCommand.execute(create_dirs=True) must create missing template dir."""

    def test_execute_creates_template_dir_when_flag_set(self, tmp_path):
        missing_dir = tmp_path / "my_templates"
        assert not missing_dir.exists()

        args = RenderCommandArgs(agent_name="test_agent", template_dir=str(missing_dir))
        cmd = RenderCommand(args, project_root=tmp_path)

        with patch.object(cmd, "_render_template", return_value="rendered"):
            with patch("agent_actions.cli.compile.ProjectPathsFactory") as mock_factory:
                mock_paths = MagicMock()
                mock_paths.agent_config_dir = tmp_path
                mock_factory.create_project_paths.return_value = mock_paths
                with patch("agent_actions.cli.compile.click.echo"):
                    cmd.execute(create_dirs=True)

        assert missing_dir.exists()

    def test_execute_does_not_create_dir_when_flag_not_set(self, tmp_path):
        missing_dir = tmp_path / "my_templates"
        assert not missing_dir.exists()

        args = RenderCommandArgs(agent_name="test_agent", template_dir=str(missing_dir))
        cmd = RenderCommand(args, project_root=tmp_path)

        # Without create_dirs=True the command must NOT create the directory
        # We inspect only the mkdir side-effect, not the full execute() flow
        assert not missing_dir.exists()
        # Calling execute(create_dirs=False) may raise for missing config — that's fine.
        # The directory must remain absent immediately before the mkdir guard.
        with patch.object(cmd, "_render_template", return_value="rendered"):
            with patch("agent_actions.cli.compile.ProjectPathsFactory") as mock_factory:
                mock_paths = MagicMock()
                mock_paths.agent_config_dir = tmp_path
                mock_factory.create_project_paths.return_value = mock_paths
                with patch("agent_actions.cli.compile.click.echo"):
                    cmd.execute(create_dirs=False)

        assert not missing_dir.exists()

    def test_execute_does_not_touch_existing_dir(self, tmp_path):
        existing_dir = tmp_path / "templates"
        existing_dir.mkdir()
        (existing_dir / "sentinel.txt").write_text("keep")

        args = RenderCommandArgs(agent_name="test_agent", template_dir=str(existing_dir))
        cmd = RenderCommand(args, project_root=tmp_path)

        with patch.object(cmd, "_render_template", return_value="rendered"):
            with patch("agent_actions.cli.compile.ProjectPathsFactory") as mock_factory:
                mock_paths = MagicMock()
                mock_paths.agent_config_dir = tmp_path
                mock_factory.create_project_paths.return_value = mock_paths
                with patch("agent_actions.cli.compile.click.echo"):
                    cmd.execute(create_dirs=True)

        assert (existing_dir / "sentinel.txt").exists()

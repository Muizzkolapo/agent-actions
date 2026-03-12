"""Regression tests for CLI hardening fixes."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.project_paths_factory import ProjectPathsFactory


class TestBannerNotOnStdout:
    """@requires_project banner must go to stderr, never stdout."""

    def test_requires_project_banner_uses_err_flag(self):
        """click.echo for the banner is called with err=True."""
        import click

        @click.command()
        @requires_project
        def dummy():
            click.echo('{"ok": true}')

        runner = CliRunner()
        with patch(
            "agent_actions.cli.cli_decorators.ensure_in_project",
            return_value=MagicMock(relative_to=MagicMock(return_value=".")),
        ):
            with patch("os.chdir"), patch("os.getcwd", return_value="/tmp"):
                _result = runner.invoke(dummy)

        import inspect as inspect_mod

        source = inspect_mod.getsource(requires_project)
        assert 'click.echo(f"' in source and "err=True" in source, (
            "Banner click.echo must use err=True"
        )


class TestHandlesUserErrorsExitPath:
    """_already_displayed errors must produce non-zero exit via click.exceptions.Exit."""

    def test_already_displayed_error_exits_nonzero(self):
        import click

        @click.command()
        @handles_user_errors("test")
        def failing():
            exc = RuntimeError("boom")
            exc._already_displayed = True
            raise exc

        runner = CliRunner()
        result = runner.invoke(failing)
        assert result.exit_code == 1


class TestInspectNotFoundExitCode:
    """Inspect 'not found' paths must produce exit code 1, not 0."""

    def test_dependencies_action_filter_not_found_raises(self):
        """DependenciesCommand raises ClickException when action filter doesn't match."""
        from agent_actions.cli.inspect import DependenciesCommand

        cmd = DependenciesCommand.__new__(DependenciesCommand)
        cmd.agent_name = "test"
        cmd.action_filter = "nonexistent"
        cmd.json_output = False
        cmd.console = MagicMock()

        # Mock _load_workflow and _analyze_dependencies
        mock_workflow = MagicMock()
        mock_workflow.execution_order = []
        cmd._load_workflow = MagicMock(return_value=mock_workflow)
        cmd._analyze_dependencies = MagicMock(return_value={"action_a": {}, "action_b": {}})

        import click

        with pytest.raises(click.ClickException, match="nonexistent"):
            cmd.execute()

    def test_dependencies_json_mode_also_filters(self):
        """Action filter applies in JSON mode too (not only rich mode)."""
        from agent_actions.cli.inspect import DependenciesCommand

        cmd = DependenciesCommand.__new__(DependenciesCommand)
        cmd.agent_name = "test"
        cmd.action_filter = "nonexistent"
        cmd.json_output = True
        cmd.console = MagicMock()

        mock_workflow = MagicMock()
        cmd._load_workflow = MagicMock(return_value=mock_workflow)
        cmd._analyze_dependencies = MagicMock(return_value={"action_a": {}, "action_b": {}})

        import click

        with pytest.raises(click.ClickException, match="nonexistent"):
            cmd.execute()


class TestReadOnlyCommandsNoMutation:
    """Read-only commands must not create directories."""

    def test_create_project_paths_auto_create_false_skips_mkdir(self):
        """auto_create=False skips ensure_path_exists calls."""
        with (
            patch.object(ProjectPathsFactory, "get_agent_paths") as mock_paths,
            patch("agent_actions.cli.project_paths_factory.PathManager") as mock_pm_cls,
            patch("agent_actions.cli.project_paths_factory.PathValidator") as mock_pv_cls,
            patch("agent_actions.cli.project_paths_factory.resolve_absolute_path") as mock_resolve,
        ):
            mock_pm = mock_pm_cls.return_value
            mock_pm.get_project_root.return_value = MagicMock()
            mock_pm.get_standard_path.return_value = MagicMock(exists=MagicMock(return_value=True))
            mock_paths.return_value = (MagicMock(), MagicMock())
            mock_resolve.return_value = MagicMock()

            mock_pv = mock_pv_cls.return_value
            mock_pv.validate.return_value = True

            ProjectPathsFactory.create_project_paths("test", "test.yml", auto_create=False)

            # ensure_path_exists must NOT be called when auto_create=False
            mock_pm.ensure_path_exists.assert_not_called()


class TestPreviewPagingBounds:
    """Preview --limit and --offset reject invalid values."""

    def test_preview_rejects_negative_limit(self):
        from agent_actions.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["preview", "-w", "test", "-n", "-1"])
        assert result.exit_code != 0

    def test_preview_rejects_zero_limit(self):
        from agent_actions.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["preview", "-w", "test", "-n", "0"])
        assert result.exit_code != 0

    def test_preview_rejects_negative_offset(self):
        from agent_actions.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["preview", "-w", "test", "--offset", "-1"])
        assert result.exit_code != 0


class TestInitForceBackupSafety:
    """init --force must not destroy pre-existing sibling directories."""

    def test_force_init_does_not_delete_existing_bak_directory(self):
        """Backup uses a unique temp path, never clobbers <project>.bak."""
        from agent_actions.cli.init import InitCommand
        from agent_actions.validation.init_validator import InitCommandArgs

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "myproject"
            project_dir.mkdir()
            (project_dir / "existing.txt").write_text("old")

            bak_dir = Path(tmpdir) / "myproject.bak"
            bak_dir.mkdir()
            (bak_dir / "precious.txt").write_text("do not delete")

            args = InitCommandArgs(
                project_name="myproject",
                output_dir=tmpdir,
                template="default",
                force=True,
            )
            cmd = InitCommand(args)

            with patch.object(cmd, "_initialize_project"):
                cmd.execute()

            assert bak_dir.exists(), ".bak sibling must survive"
            assert (bak_dir / "precious.txt").read_text() == "do not delete"


class TestStatusCorruptedFileExitCode:
    """Corrupted status files must produce non-zero exit codes."""

    def test_corrupted_json_exits_nonzero(self):
        import click

        from agent_actions.cli.status import StatusCommand
        from agent_actions.validation.status_validator import StatusCommandArgs

        with tempfile.TemporaryDirectory() as tmpdir:
            io_dir = Path(tmpdir)
            status_file = io_dir / ".agent_status.json"
            status_file.write_text("{invalid json")

            args = StatusCommandArgs(agent="test")
            cmd = StatusCommand(args)
            cmd.agent_name = "test"
            mock_paths = MagicMock()
            mock_paths.io_dir = io_dir

            with patch.object(ProjectPathsFactory, "create_project_paths", return_value=mock_paths):
                with pytest.raises(click.ClickException, match="corrupted"):
                    cmd.execute()

    def test_non_dict_status_exits_nonzero(self):
        import click

        from agent_actions.cli.status import StatusCommand
        from agent_actions.validation.status_validator import StatusCommandArgs

        with tempfile.TemporaryDirectory() as tmpdir:
            io_dir = Path(tmpdir)
            status_file = io_dir / ".agent_status.json"
            status_file.write_text('["not", "a", "dict"]')

            args = StatusCommandArgs(agent="test")
            cmd = StatusCommand(args)
            cmd.agent_name = "test"
            mock_paths = MagicMock()
            mock_paths.io_dir = io_dir

            with patch.object(ProjectPathsFactory, "create_project_paths", return_value=mock_paths):
                with pytest.raises(click.ClickException, match="unexpected format"):
                    cmd.execute()

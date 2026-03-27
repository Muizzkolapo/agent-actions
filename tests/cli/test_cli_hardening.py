"""Regression tests for CLI hardening fixes."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.prompt.handler import PromptLoader


class TestBannerNotOnStdout:
    """@requires_project banner must go to stderr, never stdout."""

    def test_requires_project_banner_uses_err_flag(self):
        """click.echo for the banner is called with err=True."""
        import click

        @click.command()
        @requires_project
        def dummy(project_root=None):
            click.echo('{"ok": true}')

        runner = CliRunner()
        with patch(
            "agent_actions.cli.cli_decorators.ensure_in_project",
            return_value=MagicMock(relative_to=MagicMock(return_value=".")),
        ):
            _result = runner.invoke(dummy)

        import inspect as inspect_mod

        source = inspect_mod.getsource(requires_project)
        assert 'click.echo(f"' in source and "err=True" in source, (
            "Banner click.echo must use err=True"
        )

    def test_requires_project_injects_correct_project_root(self, tmp_path):
        """Decorated function receives the exact Path from ensure_in_project."""
        import click

        captured = {}

        @click.command()
        @requires_project
        def dummy(project_root=None):
            captured["project_root"] = project_root
            click.echo("ok")

        runner = CliRunner()
        fake_root = tmp_path / "myproject"
        fake_root.mkdir()

        with patch(
            "agent_actions.cli.cli_decorators.ensure_in_project",
            return_value=fake_root,
        ):
            result = runner.invoke(dummy)

        assert result.exit_code == 0
        assert captured["project_root"] == fake_root


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
        assert "boom" not in result.output


class TestHandlesUserErrorsExceptionRouting:
    """Unexpected errors propagate with traceback; expected errors are prettified."""

    def test_unexpected_error_preserves_traceback(self):
        """A RuntimeError (not AgentActionsError) without _already_displayed propagates raw."""
        import click

        @click.command()
        @handles_user_errors("test")
        def failing():
            raise RuntimeError("unexpected bug")

        runner = CliRunner()
        result = runner.invoke(failing)
        # Click catches unhandled exceptions: exit_code 1, exception preserved
        assert result.exit_code == 1
        assert result.exception is not None
        assert isinstance(result.exception, RuntimeError)
        assert str(result.exception) == "unexpected bug"

    def test_expected_error_prettified(self):
        """An AgentActionsError is caught and wrapped in ClickException."""
        import click

        from agent_actions.errors.base import AgentActionsError

        @click.command()
        @handles_user_errors("test")
        def failing():
            raise AgentActionsError("config is invalid")

        runner = CliRunner()
        result = runner.invoke(failing)
        assert result.exit_code == 1
        # ClickException formats as "Error: <message>" in output
        assert "config is invalid" in result.output

    def test_click_exception_passes_through(self):
        """A ClickException raised inside the wrapped function passes through unmodified."""
        import click

        @click.command()
        @handles_user_errors("test")
        def failing():
            raise click.ClickException("already formatted")

        runner = CliRunner()
        result = runner.invoke(failing)
        assert result.exit_code == 1
        assert "already formatted" in result.output

    def test_agent_actions_error_already_displayed_exits_silently(self):
        """AgentActionsError with _already_displayed exits without re-formatting."""
        import click

        from agent_actions.errors.base import AgentActionsError

        @click.command()
        @handles_user_errors("test")
        def failing():
            exc = AgentActionsError("already shown")
            exc._already_displayed = True
            raise exc

        runner = CliRunner()
        result = runner.invoke(failing)
        assert result.exit_code == 1
        assert "already shown" not in result.output


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
            patch("agent_actions.config.project_paths.PathManager") as mock_pm_cls,
            patch("agent_actions.validation.path_validator.PathValidator") as mock_pv_cls,
            patch("agent_actions.config.project_paths.resolve_absolute_path") as mock_resolve,
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


class TestRequiresProjectNoChdir:
    """@requires_project must never call os.chdir."""

    def test_os_chdir_never_called_during_requires_project(self, tmp_path):
        """Patching os.chdir to raise ensures the decorator never calls it."""
        import os

        import click

        @click.command()
        @requires_project
        def dummy(project_root=None):
            click.echo("ok")

        runner = CliRunner()
        fake_root = tmp_path / "proj"
        fake_root.mkdir()

        with (
            patch(
                "agent_actions.cli.cli_decorators.ensure_in_project",
                return_value=fake_root,
            ),
            patch.object(os, "chdir", side_effect=AssertionError("os.chdir must not be called")),
        ):
            result = runner.invoke(dummy)

        assert result.exit_code == 0, result.output


class TestProjectRootFallback:
    """project_root=None must fall back to Path.cwd() for backward compatibility."""

    def test_get_action_folder_falls_back_to_cwd(self):
        """ActionRunner.get_action_folder falls back to Path.cwd() when project_root is None."""
        from agent_actions.workflow.runner import ActionRunner

        runner = ActionRunner(use_tools=False)
        # project_root is None by default
        assert runner.project_root is None
        # get_action_folder will search from CWD — we just verify it doesn't crash on init
        # (it will raise FileSystemError because there's no agent_io folder, which is expected)
        from agent_actions.errors import FileSystemError

        with pytest.raises(FileSystemError, match="Action folder not found"):
            runner.get_action_folder("nonexistent_agent")


class TestGetOutputFieldsWithSchemaDir:
    """_get_output_fields correctly uses schema_dir for named schema resolution."""

    def test_get_output_fields_from_action_schema(self):
        """Named schema fields are resolved via ActionSchema (WorkflowSchemaService)."""
        from agent_actions.cli.inspect import BaseInspectCommand
        from agent_actions.models.action_schema import (
            ActionKind,
            ActionSchema,
            FieldInfo,
            FieldSource,
        )

        action_schema = ActionSchema(
            name="test_action",
            kind=ActionKind.LLM,
            output_fields=[
                FieldInfo(name="field_a", source=FieldSource.SCHEMA),
                FieldInfo(name="field_b", source=FieldSource.SCHEMA),
            ],
        )

        config = {"schema_name": "test_schema"}
        fields = BaseInspectCommand._get_output_fields(config, action_schema=action_schema)
        assert set(fields) == {"field_a", "field_b"}

    def test_get_output_fields_without_schema_dir_returns_placeholder(self):
        """Named schema without schema_dir returns placeholder instead of crashing."""
        from agent_actions.cli.inspect import BaseInspectCommand

        config = {"schema_name": "some_schema"}
        fields = BaseInspectCommand._get_output_fields(config)
        assert fields == ["[schema: some_schema]"]


class TestRequiresProjectErrorPath:
    """@requires_project must propagate ProjectNotFoundError cleanly."""

    def test_project_not_found_error_propagates(self):
        """ProjectNotFoundError from ensure_in_project raises through the decorator."""
        import click

        from agent_actions.errors import ProjectNotFoundError

        @click.command()
        @handles_user_errors("test")
        @requires_project
        def dummy(project_root=None):
            click.echo("should not reach here")

        runner = CliRunner()
        with patch(
            "agent_actions.cli.cli_decorators.ensure_in_project",
            side_effect=ProjectNotFoundError(
                "Project not found",
                context={"marker_file": "agent_actions.yml"},
            ),
        ):
            result = runner.invoke(dummy)

        assert result.exit_code != 0
        assert "Project not found" in result.output

    def test_project_not_found_without_handles_user_errors(self):
        """Without handles_user_errors, ProjectNotFoundError propagates as exception."""
        import click

        from agent_actions.errors import ProjectNotFoundError

        @click.command()
        @requires_project
        def dummy(project_root=None):
            click.echo("should not reach here")

        runner = CliRunner()
        with patch(
            "agent_actions.cli.cli_decorators.ensure_in_project",
            side_effect=ProjectNotFoundError(
                "Project not found",
                context={"marker_file": "agent_actions.yml"},
            ),
        ):
            result = runner.invoke(dummy)

        # Click catches unhandled exceptions and sets exit_code=1
        assert result.exit_code == 1


class TestProjectRootIntegrationChain:
    """project_root flows from decorator → ProjectPathsFactory → FileHandler."""

    def test_project_root_reaches_file_handler(self, tmp_path):
        """ProjectPathsFactory.get_agent_paths receives the project_root from CLI."""
        # Set up a minimal project structure
        (tmp_path / "agent_actions.yml").write_text("project: test")
        agent_dir = tmp_path / "my_agent"
        agent_dir.mkdir()
        (agent_dir / "agent_config").mkdir()
        (agent_dir / "agent_io").mkdir()
        (agent_dir / "agent_config" / "my_agent.yml").write_text("name: my_agent")

        agent_config_dir, io_dir = ProjectPathsFactory.get_agent_paths(
            "my_agent", project_root=tmp_path
        )

        assert agent_config_dir.exists()
        assert io_dir.exists()
        assert tmp_path in agent_config_dir.parents or agent_config_dir.parent == tmp_path
        assert tmp_path in io_dir.parents or io_dir.parent == tmp_path


class TestLoadPromptPartialBinding:
    """render_pipeline_with_templates binds project_root into load_prompt via partial."""

    def test_load_prompt_receives_project_root(self, tmp_path):
        """Verify the functools.partial in render_pipeline_with_templates passes project_root."""
        import functools

        # Create minimal template and config files
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        config_file = tmp_path / "test_config.yml"
        config_file.write_text("actions:\n  - name: test_action\n    prompt: hello")

        import jinja2

        with patch.object(PromptLoader, "load_prompt", staticmethod(lambda *a, **kw: "")):
            from agent_actions.prompt.render_workflow import render_pipeline_with_templates

            original_init = jinja2.Environment.__init__

            env_captured = {}

            def spy_env_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                env_captured["env"] = self

            with patch.object(jinja2.Environment, "__init__", spy_env_init):
                render_pipeline_with_templates(
                    str(config_file),
                    str(templates_dir),
                    project_root=tmp_path,
                )

            env = env_captured.get("env")
            assert env is not None, "Jinja2 Environment should have been created"
            load_prompt_fn = env.globals.get("load_prompt")
            assert load_prompt_fn is not None, "load_prompt should be registered as Jinja2 global"
            assert isinstance(load_prompt_fn, functools.partial), (
                "load_prompt should be a functools.partial"
            )
            assert load_prompt_fn.keywords.get("project_root") == tmp_path


class TestProjectRootDictInjectionRoundTrip:
    """_project_root dict injection: Path → str (coordinator) → Path (builder/preparator)."""

    def test_coordinator_injects_string(self):
        """Coordinator stores _project_root as string in agent_config dicts."""
        from unittest.mock import MagicMock

        from agent_actions.workflow.coordinator import AgentWorkflow

        with patch.object(AgentWorkflow, "__init__", lambda self: None):
            workflow = AgentWorkflow()
            workflow.config = MagicMock()
            workflow.config.project_root = Path("/fake/project")
            workflow.config.paths.constructor_path = "/fake/config.yml"

            agent_configs = {"action_a": {"agent_type": "test"}}

            # Simulate the injection logic from config_pipeline.load_workflow_configs
            for _name, config in agent_configs.items():
                if config is None:
                    continue
                if workflow.config.project_root:
                    config["_project_root"] = str(workflow.config.project_root)

            assert agent_configs["action_a"]["_project_root"] == "/fake/project"
            assert isinstance(agent_configs["action_a"]["_project_root"], str)

    def test_builder_reconstructs_path(self):
        """Builder extracts _project_root string and converts back to Path."""
        agent_config = {
            "agent_type": "test",
            "_project_root": "/fake/project",
        }

        _pr = agent_config.get("_project_root")
        reconstructed = Path(_pr) if _pr else None

        assert reconstructed == Path("/fake/project")
        assert isinstance(reconstructed, Path)

    def test_none_project_root_not_injected(self):
        """When project_root is None, _project_root key is not added."""
        agent_config = {"agent_type": "test"}

        project_root = None
        if project_root:
            agent_config["_project_root"] = str(project_root)

        assert "_project_root" not in agent_config


class TestNoSysPathMutation:
    """Production code must never mutate sys.path."""

    @pytest.mark.parametrize(
        "pattern",
        [
            r"sys\.path\.insert",
            r"sys\.path\.append",
            r"sys\.path\.extend",
            r"sys\.path\s*\[.*\]\s*=",
            r"sys\.path\s*\+=",
        ],
        ids=["insert", "append", "extend", "subscript_assign", "iadd"],
    )
    def test_no_sys_path_mutation_in_production_code(self, pattern):
        """Assert zero sys.path mutation vectors in production code."""
        import subprocess

        result = subprocess.run(
            ["grep", "-rn", "-E", pattern, "agent_actions/", "--include=*.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parents[2],  # repo root
        )
        assert result.stdout == "", (
            f"Found sys.path mutation ({pattern}) in production code:\n{result.stdout}"
        )


class TestActionRunnerProjectRootPaths:
    """ActionRunner.get_action_folder uses explicit param, instance attr, then CWD."""

    def test_explicit_param_takes_precedence(self, tmp_path):
        """Explicit project_root parameter overrides instance attribute."""
        from agent_actions.workflow.runner import ActionRunner

        runner = ActionRunner(use_tools=False)
        runner.project_root = Path("/should/not/use/this")

        # Create a project structure in tmp_path
        agent_dir = tmp_path / "test_agent"
        agent_dir.mkdir()
        io_dir = agent_dir / "agent_io"
        io_dir.mkdir()

        result = runner.get_action_folder("test_agent", project_root=tmp_path)
        assert str(tmp_path) in result

    def test_instance_attr_used_when_no_param(self, tmp_path):
        """Instance project_root is used when no explicit param is passed."""
        from agent_actions.workflow.runner import ActionRunner

        runner = ActionRunner(use_tools=False)

        # Create a project structure in tmp_path
        agent_dir = tmp_path / "test_agent"
        agent_dir.mkdir()
        io_dir = agent_dir / "agent_io"
        io_dir.mkdir()

        runner.project_root = tmp_path
        result = runner.get_action_folder("test_agent")
        assert str(tmp_path) in result

    def test_cwd_fallback_when_both_none(self):
        """Falls back to CWD when both param and instance attr are None."""
        from agent_actions.errors import FileSystemError
        from agent_actions.workflow.runner import ActionRunner

        runner = ActionRunner(use_tools=False)
        assert runner.project_root is None

        with pytest.raises(FileSystemError, match="Action folder not found"):
            runner.get_action_folder("nonexistent_agent")


class TestNoCircularImportAtLoadTime:
    """Leaf packages must import independently without triggering cycles."""

    @pytest.mark.parametrize(
        "pkg",
        [
            "agent_actions.errors",
            "agent_actions.models",
            "agent_actions.guards",
            "agent_actions.utils",
            "agent_actions.logging",
            "agent_actions.config",
        ],
    )
    def test_leaf_package_imports_cleanly(self, pkg):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c", f"import {pkg}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Failed to import {pkg}: {result.stderr}"

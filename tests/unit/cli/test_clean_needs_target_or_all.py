"""``agac clean`` removes nothing unless ``--target`` or ``--all`` says what to remove.

``target/`` holds paid per-action output, so it goes only with ``--target`` or
``--all``. No flag removes ``source/``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from agent_actions.cli.clean import clean_cli
from agent_actions.cli.main import cli
from agent_actions.llm.realtime.cleaner import Cleaner


def _make_cleaner(tmp_path: Path, **kwargs) -> tuple[Cleaner, MagicMock]:
    """Build a Cleaner over a fake agent_io tree with a mocked AgentManager."""
    io_dir = tmp_path / "agent_io"
    for sub in ("source", "target", "staging", "store"):
        (io_dir / sub).mkdir(parents=True)
    agent_manager = MagicMock()
    agent_manager.get_agent_paths.return_value = (
        str(io_dir / "agent_config"),
        str(io_dir),
        str(io_dir / "logs"),
    )
    cleaner = Cleaner(agent="wf", project_root=tmp_path, agent_manager=agent_manager, **kwargs)
    return cleaner, agent_manager


def _cleaned_names(agent_manager: MagicMock) -> set[str]:
    return {Path(call.args[1]).name for call in agent_manager.clean_directory.call_args_list}


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    workflow = tmp_path / "agent_workflow" / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "wf.yml").write_text("name: wf\nactions: []\n")
    for sub in ("source", "target", "staging"):
        (workflow / "agent_io" / sub).mkdir(parents=True)
        (workflow / "agent_io" / sub / "kept.json").write_text("[]")
    monkeypatch.chdir(tmp_path)
    return workflow / "agent_io"


def _kept(io_dir: Path) -> set[str]:
    return {p.parent.name for p in io_dir.glob("*/kept.json")}


@pytest.mark.parametrize(
    "args",
    [[], ["-a", "wf"], ["-a", "wf", "--force"]],
    ids=["bare", "workflow", "force"],
)
def test_clean_without_target_or_all_lists_the_choices_and_removes_nothing(project, args):
    result = CliRunner().invoke(cli, ["clean", *args])

    assert result.exit_code == 2
    assert "Give --target or --all to say what to clean" in result.stderr
    for choice in ("--target", "--all", "--force"):
        assert choice in result.stderr
    assert _kept(project) == {"source", "target", "staging"}
    assert not (project / "store").exists()


def test_clean_without_target_or_all_lists_the_choices_outside_a_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["clean"])

    assert result.exit_code == 2
    assert "Give --target or --all to say what to clean" in result.stderr


@pytest.mark.parametrize("flag", ["--target", "--all"])
def test_a_scope_without_a_workflow_names_the_option_it_lacks(project, flag):
    result = CliRunner().invoke(cli, ["clean", flag])

    assert result.exit_code == 2
    assert "Missing option '-w' / '--workflow' / '-a'." in result.stderr
    assert _kept(project) == {"source", "target", "staging"}


def test_clean_target_removes_target_only(project):
    result = CliRunner().invoke(cli, ["clean", "-a", "wf", "--target", "--force"])

    assert result.exit_code == 0, result.output
    assert _kept(project) == {"source", "staging"}


def test_clean_all_removes_target_and_staging_and_keeps_source(project):
    result = CliRunner().invoke(cli, ["clean", "-a", "wf", "--all", "--force"])

    assert result.exit_code == 0, result.output
    assert _kept(project) == {"source"}


def test_the_cleaner_with_no_scope_removes_nothing(tmp_path):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=True)
    cleaner.run()
    assert _cleaned_names(agent_manager) == set()


def test_target_confirmation_lists_only_target(tmp_path, monkeypatch, capsys):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=False, remove_target=True)
    monkeypatch.setattr("click.confirm", lambda *args, **kwargs: False)
    cleaner.run()
    listed = [line for line in capsys.readouterr().out.splitlines() if "•" in line]
    assert [Path(line.split("•")[1].strip()).name for line in listed] == ["target"]
    agent_manager.clean_directory.assert_not_called()


def test_target_flag_removes_target(tmp_path):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=True, remove_target=True)
    cleaner.run()
    assert _cleaned_names(agent_manager) == {"target"}


def test_all_still_removes_everything_but_source(tmp_path):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=True, remove_all=True)
    cleaner.run()
    assert _cleaned_names(agent_manager) == {"target", "staging", "store"}


def test_target_with_all_is_still_full_removal(tmp_path):
    cleaner, agent_manager = _make_cleaner(
        tmp_path, force=True, remove_target=True, remove_all=True
    )
    cleaner.run()
    assert _cleaned_names(agent_manager) == {"target", "staging", "store"}


def test_cli_exposes_target_flag():
    opt = next((p for p in clean_cli.params if getattr(p, "name", None) == "remove_target"), None)
    assert opt is not None, "clean must expose a --target flag"
    assert "output" in opt.help.lower(), "--target help must say it removes generated output"


def test_command_help_names_no_source_directory():
    assert "source" not in clean_cli.help


def test_help_still_marks_the_workflow_required():
    result = CliRunner().invoke(cli, ["clean", "--help"])

    assert result.exit_code == 0
    line = next(line for line in result.stdout.splitlines() if "--workflow" in line)
    assert "-a" in line
    assert "[required]" in result.stdout

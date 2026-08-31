"""``agac clean``'s default scope must not delete generated output.

``target/`` holds paid per-action output; ``source/`` is rebuilt from
``staging/`` on the next run. Contract: default removes source only,
``--target`` opts into output removal, ``--all`` stays full removal.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest

from agent_actions.cli.clean import clean_cli
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


def test_default_removes_source_only(tmp_path):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=True)
    cleaner.run()
    names = _cleaned_names(agent_manager)
    assert names == {"source"}, f"default scope must be source only, got {names}"


def test_default_confirmation_lists_only_source(tmp_path, monkeypatch, capsys):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=False)
    monkeypatch.setattr(click, "confirm", lambda *args, **kwargs: False)
    cleaner.run()
    out = capsys.readouterr().out
    listed = [line for line in out.splitlines() if line.strip().startswith("•")]
    assert any(line.rstrip().endswith("source") for line in listed)
    assert not any(line.rstrip().endswith("target") for line in listed), (
        f"confirmation must not list target/ for a default clean, output was:\n{out}"
    )
    agent_manager.clean_directory.assert_not_called()


def test_target_flag_removes_source_and_target(tmp_path):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=True, remove_target=True)
    cleaner.run()
    names = _cleaned_names(agent_manager)
    assert names == {"source", "target"}, f"--target scope must be source+target, got {names}"


def test_all_still_removes_everything(tmp_path):
    """Regression: explicit --all callers keep today's full-removal behaviour."""
    cleaner, agent_manager = _make_cleaner(tmp_path, force=True, remove_all=True)
    cleaner.run()
    assert _cleaned_names(agent_manager) == {"source", "target", "staging", "store"}


def test_target_with_all_is_still_full_removal(tmp_path):
    cleaner, agent_manager = _make_cleaner(
        tmp_path, force=True, remove_target=True, remove_all=True
    )
    cleaner.run()
    assert _cleaned_names(agent_manager) == {"source", "target", "staging", "store"}


def test_cli_exposes_target_flag():
    opt = next((p for p in clean_cli.params if getattr(p, "name", None) == "remove_target"), None)
    assert opt is not None, "clean must expose a --target flag"
    assert "output" in opt.help.lower(), "--target help must say it removes generated output"


def test_command_help_describes_source_only_default():
    assert "source and target" not in clean_cli.help, (
        "command help still claims the default removes target/"
    )
    assert "source" in clean_cli.help


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

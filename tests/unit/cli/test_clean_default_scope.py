"""``agac clean``'s scope must not delete generated output by accident.

``target/`` holds paid per-action output, so it stays behind ``--target``;
``--all`` stays full removal. Nothing writes ``agent_io/source/`` any more, so
a bare ``agac clean`` names the flags that do something rather than reporting
success over an empty list.
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


def test_a_bare_clean_names_the_flags_that_do_something(tmp_path):
    """Nothing writes source/ any more, so the old default has nothing to remove.
    Reporting success over an empty list reads as 'cleaned' to a script."""
    cleaner, agent_manager = _make_cleaner(tmp_path, force=True)

    with pytest.raises(click.ClickException) as exc:
        cleaner.run()

    message = str(exc.value)
    assert "--target" in message and "--all" in message
    agent_manager.clean_directory.assert_not_called()


def test_target_flag_removes_generated_output(tmp_path):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=True, remove_target=True)
    cleaner.run()
    names = _cleaned_names(agent_manager)
    assert names == {"target"}, f"--target scope must be target, got {names}"


def test_target_confirmation_lists_what_it_will_remove(tmp_path, monkeypatch, capsys):
    cleaner, agent_manager = _make_cleaner(tmp_path, force=False, remove_target=True)
    monkeypatch.setattr(click, "confirm", lambda *args, **kwargs: False)
    cleaner.run()
    out = capsys.readouterr().out
    listed = [line for line in out.splitlines() if line.strip().startswith("•")]
    assert any(line.rstrip().endswith("target") for line in listed)
    agent_manager.clean_directory.assert_not_called()


def test_all_still_removes_everything(tmp_path):
    """Regression: explicit --all callers keep today's full-removal behaviour."""
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


def test_command_help_does_not_promise_a_default_removal():
    assert "source directory" not in clean_cli.help, (
        "command help still describes a directory nothing writes"
    )
    assert "--target" in clean_cli.help and "--all" in clean_cli.help


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

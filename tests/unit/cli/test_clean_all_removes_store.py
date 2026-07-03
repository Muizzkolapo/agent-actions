"""Regression test for VIOL-0043: `agac clean --all` must remove store/.

Today the ``remove_all`` branch only appends ``staging/``; the SQLite
``store/`` directory is silently preserved, so ``--all`` does not mean all and
an old run's database pollutes the next. These tests pin the invariant that
``--all`` removes ``store/`` (and lists it in the confirmation prompt), while
plain ``clean`` (no ``--all``) stays source+target only.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest

from agent_actions.llm.realtime.cleaner import Cleaner


def _make_cleaner(tmp_path: Path, *, remove_all: bool, force: bool) -> tuple[Cleaner, MagicMock]:
    """Build a Cleaner over a fake agent_io tree with a mocked AgentManager.

    Returns the cleaner and the agent_manager mock so tests can inspect which
    directories were passed to ``clean_directory``.
    """
    io_dir = tmp_path / "agent_io"
    for sub in ("source", "target", "staging", "store"):
        (io_dir / sub).mkdir(parents=True)
    agent_manager = MagicMock()
    agent_manager.get_agent_paths.return_value = (
        str(io_dir / "agent_config"),
        str(io_dir),
        str(io_dir / "logs"),
    )
    cleaner = Cleaner(
        agent="wf",
        force=force,
        remove_all=remove_all,
        project_root=tmp_path,
        agent_manager=agent_manager,
    )
    return cleaner, agent_manager


def _cleaned_names(agent_manager: MagicMock) -> set[str]:
    """Directory names actually handed to clean_directory(agent, directory)."""
    return {Path(call.args[1]).name for call in agent_manager.clean_directory.call_args_list}


def test_all_removes_store(tmp_path):
    cleaner, agent_manager = _make_cleaner(tmp_path, remove_all=True, force=True)
    cleaner.run()
    names = _cleaned_names(agent_manager)
    assert "store" in names, f"--all must remove store/, got {names}"
    assert names == {"source", "target", "staging", "store"}


def test_no_all_preserves_store(tmp_path):
    """Baseline: without --all, only source+target are removed (store survives)."""
    cleaner, agent_manager = _make_cleaner(tmp_path, remove_all=False, force=True)
    cleaner.run()
    names = _cleaned_names(agent_manager)
    assert "store" not in names
    assert "staging" not in names
    assert names == {"source", "target"}


def test_all_confirmation_lists_store(tmp_path, monkeypatch, capsys):
    """The interactive confirmation must name store/ so the wipe is explicit.

    Decline the prompt: nothing is removed, but store/ was shown to the user.
    """
    cleaner, agent_manager = _make_cleaner(tmp_path, remove_all=True, force=False)
    monkeypatch.setattr(click, "confirm", lambda *args, **kwargs: False)
    cleaner.run()
    out = capsys.readouterr().out
    assert "store" in out, f"confirmation must list store/, output was:\n{out}"
    agent_manager.clean_directory.assert_not_called()


def test_all_help_names_store_as_unrecoverable():
    """The --all help text must name store/ and warn it is unrecoverable."""
    from agent_actions.cli.clean import clean_cli

    all_opt = next(p for p in clean_cli.params if getattr(p, "name", None) == "remove_all")
    help_text = all_opt.help.lower()
    assert "store" in help_text
    assert "unrecoverable" in help_text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

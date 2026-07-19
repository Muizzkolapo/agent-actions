"""Regression test: ``agac clean --all`` must remove the durable
store — regardless of which backend owns it.

Today the ``remove_all`` branch only appends ``staging/``; the durable store
directory is silently preserved, so ``--all`` does not mean all and an old
run's data pollutes the next. These tests pin two invariants:
  * ``--all`` removes the store paths every registered backend owns.
  * Plain ``clean`` (no ``--all``) stays source+target only.

The cleaner delegates to ``StorageBackend.paths_to_wipe`` so future backends
(DuckDB, Postgres, S3) are covered without editing the CLI.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest

from agent_actions.llm.realtime.cleaner import Cleaner
from agent_actions.storage import BACKENDS
from agent_actions.storage.backend import StorageBackend
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


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


def test_all_help_is_backend_agnostic():
    """Help text must not name a specific backend — the cleaner works for all."""
    from agent_actions.cli.clean import clean_cli

    all_opt = next(p for p in clean_cli.params if getattr(p, "name", None) == "remove_all")
    assert "sqlite" not in all_opt.help.lower(), (
        "Help text names sqlite specifically; clean delegates to every "
        "registered backend and should read as generic."
    )


def test_paths_to_wipe_default_is_empty():
    """Base ``StorageBackend`` owns no filesystem paths — remote backends inherit this."""
    assert StorageBackend.paths_to_wipe(Path("/nonexistent/io")) == []


def test_sqlite_paths_to_wipe_returns_store_when_present(tmp_path):
    io_dir = tmp_path / "agent_io"
    (io_dir / "store").mkdir(parents=True)
    assert SQLiteBackend.paths_to_wipe(io_dir) == [io_dir / "store"]


def test_sqlite_paths_to_wipe_returns_empty_when_store_absent(tmp_path):
    io_dir = tmp_path / "agent_io"
    io_dir.mkdir()
    assert SQLiteBackend.paths_to_wipe(io_dir) == []


def test_all_ignores_backend_that_owns_no_paths(tmp_path, monkeypatch):
    """A backend whose ``paths_to_wipe`` returns [] contributes nothing to --all.

    Simulates a remote backend (Postgres/S3) that stores state outside io_dir.
    """

    class _RemoteBackend(StorageBackend):
        @classmethod
        def create(cls, **_kwargs):
            raise NotImplementedError

        @property
        def backend_type(self) -> str:
            return "remote"

        def initialize(self) -> None: ...
        def _write_target_raw(self, *_a, **_kw) -> str:
            return ""

        def _read_target_raw(self, *_a, **_kw):
            return []

        def _save_metadata_raw(self, *_a, **_kw) -> None: ...
        def load_metadata(self, *_a, **_kw):
            return None

        def write_source(self, *_a, **_kw) -> str:
            return ""

        def read_source(self, *_a, **_kw):
            return []

        def list_target_files(self, *_a, **_kw):
            return []

        def list_source_files(self, *_a, **_kw):
            return []

        def preview_target(self, *_a, **_kw):
            return {}

        def get_storage_stats(self):
            return {}

    monkeypatch.setitem(BACKENDS, "remote_only_test", _RemoteBackend)
    cleaner, agent_manager = _make_cleaner(tmp_path, remove_all=True, force=True)
    cleaner.run()
    names = _cleaned_names(agent_manager)
    assert names == {"source", "target", "staging", "store"}, (
        "Remote backend contributed no paths yet SQLite's store/ still gets wiped"
    )


def test_all_picks_up_extra_backend_paths(tmp_path, monkeypatch):
    """Registering a new file-based backend automatically extends --all coverage.

    This is the point of the abstraction: adding DuckDB later should not require
    editing the CLI or the cleaner.
    """
    warehouse = tmp_path / "agent_io" / "warehouse"
    warehouse.mkdir(parents=True)

    class _WarehouseBackend(StorageBackend):
        @classmethod
        def create(cls, **_kwargs):
            raise NotImplementedError

        @property
        def backend_type(self) -> str:
            return "warehouse"

        def initialize(self) -> None: ...
        def _write_target_raw(self, *_a, **_kw) -> str:
            return ""

        def _read_target_raw(self, *_a, **_kw):
            return []

        def _save_metadata_raw(self, *_a, **_kw) -> None: ...
        def load_metadata(self, *_a, **_kw):
            return None

        def write_source(self, *_a, **_kw) -> str:
            return ""

        def read_source(self, *_a, **_kw):
            return []

        def list_target_files(self, *_a, **_kw):
            return []

        def list_source_files(self, *_a, **_kw):
            return []

        def preview_target(self, *_a, **_kw):
            return {}

        def get_storage_stats(self):
            return {}

        @classmethod
        def paths_to_wipe(cls, io_dir):
            w = io_dir / "warehouse"
            return [w] if w.exists() else []

    monkeypatch.setitem(BACKENDS, "warehouse_test", _WarehouseBackend)
    cleaner, agent_manager = _make_cleaner(tmp_path, remove_all=True, force=True)
    cleaner.run()
    names = _cleaned_names(agent_manager)
    assert names == {"source", "target", "staging", "store", "warehouse"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

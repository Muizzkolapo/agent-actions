"""`agac clean` and `reset_workflow.py --full` hold the run lock while they ask and delete."""

from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest

from agent_actions.errors import RunInProgressError
from agent_actions.llm.realtime.cleaner import Cleaner
from agent_actions.llm.realtime.handlers import AgentManager
from agent_actions.storage.run_lock import hold_run_lock


def _io_dir(tmp_path: Path, *, store: bool) -> Path:
    io_dir = tmp_path / "agent_io"
    for sub in ("source", "target", "staging"):
        (io_dir / sub).mkdir(parents=True)
        (io_dir / sub / "kept.json").write_text("[]")
    if store:
        (io_dir / "store").mkdir()
        (io_dir / "store" / "wf.db").write_text("")
    return io_dir


def _lock_is_held(io_dir: Path) -> bool:
    try:
        with hold_run_lock(io_dir, "wf"):
            return False
    except RunInProgressError:
        return True


def _cleaner(io_dir: Path, seen: list[str] | None, **flags) -> Cleaner:
    """A cleaner over *io_dir*; with *seen*, each delete records whether the lock is held.

    The probe takes the lock itself when it is free, so it is left out where the test
    reads what the store holds afterwards.
    """
    manager = MagicMock()
    manager.get_agent_paths.return_value = ("", str(io_dir), "")

    def clean_directory(agent, directory, **kwargs):
        if seen is not None:
            seen.append(f"delete held={_lock_is_held(io_dir)}")
        AgentManager.clean_directory(agent, directory, **kwargs)

    manager.clean_directory.side_effect = clean_directory
    return Cleaner(agent="wf", agent_manager=manager, **flags)


@pytest.mark.parametrize("store", [True, False], ids=["store", "no-store"])
def test_the_lock_is_held_while_clean_asks_and_deletes(tmp_path, monkeypatch, store):
    """Held across the prompt: a run that starts while it waits must be refused."""
    io_dir = _io_dir(tmp_path, store=store)
    seen: list[str] = []

    def confirm(*args, **kwargs):
        seen.append(f"ask held={_lock_is_held(io_dir)}")
        return True

    monkeypatch.setattr(click, "confirm", confirm)

    _cleaner(io_dir, seen, force=False, remove_all=True).run()

    assert seen[0] == "ask held=True"
    assert seen[1:] and set(seen[1:]) == {"delete held=True"}
    assert not (io_dir / "staging").exists()


@pytest.mark.parametrize("flags", [{}, {"remove_target": True}], ids=["source", "target"])
def test_the_lock_is_held_while_a_narrower_clean_deletes(tmp_path, flags):
    io_dir = _io_dir(tmp_path, store=False)
    seen: list[str] = []

    _cleaner(io_dir, seen, force=True, **flags).run()

    assert seen and set(seen) == {"delete held=True"}


@pytest.mark.parametrize("store", [True, False], ids=["store", "no-store"])
def test_clean_all_keeps_only_the_lock_file_in_the_store(tmp_path, store):
    """The lock file is never deleted: a run that starts next locks the same file."""
    io_dir = _io_dir(tmp_path, store=store)

    _cleaner(io_dir, None, force=True, remove_all=True).run()

    assert sorted(p.name for p in (io_dir / "store").iterdir()) == ["wf.db.lock"]
    assert not (io_dir / "source").exists()
    assert not (io_dir / "target").exists()
    assert not (io_dir / "staging").exists()


def test_after_clean_the_lock_is_free(tmp_path):
    io_dir = _io_dir(tmp_path, store=True)

    _cleaner(io_dir, None, force=True, remove_all=True).run()

    assert not _lock_is_held(io_dir)


def test_a_clean_while_a_run_holds_the_lock_deletes_nothing(tmp_path, monkeypatch):
    io_dir = _io_dir(tmp_path, store=False)
    monkeypatch.setattr(click, "confirm", lambda *a, **k: pytest.fail("asked during a run"))

    with hold_run_lock(io_dir, "wf"), pytest.raises(RunInProgressError):
        _cleaner(io_dir, None, force=False, remove_all=True).run()

    assert (io_dir / "staging" / "kept.json").exists()
    assert (io_dir / "source" / "kept.json").exists()


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "agent_actions"
    / "skills"
    / "agac-agent-skills"
    / "scripts"
    / "reset_workflow.py"
)


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("reset_workflow_lock_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow(tmp_path: Path, *, store: bool) -> tuple[Path, Path]:
    root = tmp_path / "project"
    base = root / "agent_workflow" / "wf" / "agent_io"
    (base / "target").mkdir(parents=True)
    (base / "source").mkdir()
    (root / "agent_actions.yml").write_text("version: '1.0'\n")
    if store:
        (base / "store").mkdir()
        (base / "store" / "wf.db").write_text("")
    return root, base


def _without_the_framework(monkeypatch) -> None:
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name.startswith("agent_actions"):
            raise ImportError(f"refused {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)


def _full_reset(script, monkeypatch, root: Path) -> None:
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.argv", ["reset_workflow.py", "wf", "--full"])
    script.main()


def _probe_held(base: Path) -> bool:
    """Whether another holder has the lock, read with the flock both sides use."""
    import fcntl

    path = base / "store" / "wf.db.lock"
    if not path.exists():
        return False
    with open(path, "a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


@pytest.mark.parametrize("framework", [True, False], ids=["framework", "plain-python"])
@pytest.mark.parametrize("store", [True, False], ids=["store", "no-store"])
def test_the_lock_is_held_while_a_full_reset_deletes(
    script, tmp_path, monkeypatch, framework, store
):
    root, base = _workflow(tmp_path, store=store)
    seen: list[bool] = []
    real_remove = script.remove

    def remove(path):
        seen.append(_probe_held(base))
        real_remove(path)

    monkeypatch.setattr(script, "remove", remove)
    if not framework:
        _without_the_framework(monkeypatch)

    _full_reset(script, monkeypatch, root)

    assert seen and all(seen), seen
    assert not (base / "source").exists()


@pytest.mark.parametrize("framework", [True, False], ids=["framework", "plain-python"])
@pytest.mark.parametrize("store", [True, False], ids=["store", "no-store"])
def test_a_full_reset_keeps_only_the_lock_file_in_the_store(
    script, tmp_path, monkeypatch, framework, store
):
    root, base = _workflow(tmp_path, store=store)
    if not framework:
        _without_the_framework(monkeypatch)

    _full_reset(script, monkeypatch, root)

    assert sorted(p.name for p in (base / "store").iterdir()) == ["wf.db.lock"]
    assert not _probe_held(base)

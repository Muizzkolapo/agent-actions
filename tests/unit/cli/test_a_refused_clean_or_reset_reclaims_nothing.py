"""A `clean --all` or `reset --full` refused for a run in progress reclaims no batch record.

The reclaim releases what a provider recorded about the batches the store names; a
run in progress may still need them, so it happens only under the run lock.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import portalocker
import pytest

from agent_actions.errors import RunInProgressError
from agent_actions.llm.providers import local_batch_records
from agent_actions.llm.realtime.cleaner import Cleaner
from agent_actions.storage import get_storage_backend

BATCH = "mock_batch_abc123"
SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "agent_actions"
    / "skills"
    / "agac-agent-skills"
    / "scripts"
    / "reset_workflow.py"
)


def _workflow(tmp_path: Path) -> tuple[Path, Path]:
    """A project whose workflow store names one submitted batch."""
    root = tmp_path / "project"
    io_dir = root / "agent_workflow" / "wf" / "agent_io"
    (io_dir / "target").mkdir(parents=True)
    (root / "agent_actions.yml").write_text("version: '1.0'\n")
    backend = get_storage_backend(workflow_path=str(io_dir.parent), workflow_name="wf")
    backend.initialize()
    try:
        entry = {
            "batch_id": BATCH,
            "status": "completed",
            "timestamp": "t",
            "provider": "agac-provider",
        }
        backend.save_metadata("batch_registry:summarize", json.dumps({"pages.json": entry}))
    finally:
        backend.close()
    return root, io_dir


@pytest.fixture
def released(monkeypatch) -> list[str]:
    calls: list[str] = []

    def release(batch_id: str) -> bool:
        calls.append(batch_id)
        return True

    monkeypatch.setattr(local_batch_records, "release_local_batch_record", release)
    monkeypatch.setattr(local_batch_records, "discard_partial_batch_records", lambda: None)
    return calls


def _held(io_dir: Path):
    return portalocker.Lock(
        io_dir / "store" / "wf.db.lock", mode="a+", flags=portalocker.LOCK_EX | portalocker.LOCK_NB
    )


def _cleaner(io_dir: Path) -> Cleaner:
    manager = MagicMock()
    manager.get_agent_paths.return_value = ("", str(io_dir), "")
    return Cleaner(agent="wf", force=True, remove_all=True, agent_manager=manager)


def _reset(monkeypatch, root: Path) -> None:
    spec = importlib.util.spec_from_file_location("reset_workflow_reclaim_under_test", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.argv", ["reset_workflow.py", "wf", "--full"])
    script.main()


def test_a_refused_clean_reclaims_nothing(tmp_path, released):
    _, io_dir = _workflow(tmp_path)

    with _held(io_dir), pytest.raises(RunInProgressError):
        _cleaner(io_dir).run()

    assert released == []


def test_a_clean_no_run_holds_reclaims_the_batch(tmp_path, released):
    _, io_dir = _workflow(tmp_path)

    _cleaner(io_dir).run()

    assert released == [BATCH]


def test_a_refused_full_reset_reclaims_nothing(tmp_path, monkeypatch, released):
    root, io_dir = _workflow(tmp_path)

    with _held(io_dir), pytest.raises(SystemExit):
        _reset(monkeypatch, root)

    assert released == []


def test_a_full_reset_no_run_holds_reclaims_the_batch(tmp_path, monkeypatch, released):
    root, io_dir = _workflow(tmp_path)

    _reset(monkeypatch, root)

    assert released == [BATCH]

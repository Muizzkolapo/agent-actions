"""`agac clean --all` reclaims the batch records of the real store and of the sandbox store.

Each store names its own batches. A store that this version cannot read names none
that it can find, but that does not stop the reclaim of the other store. A store that
does not exist names no batch, and the reclaim does not create it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.config.sandbox import sandbox_mode, store_file
from agent_actions.llm.providers import local_batch_records
from agent_actions.llm.realtime.cleaner import Cleaner
from agent_actions.storage import get_storage_backend


@pytest.fixture
def io_dir(tmp_path: Path) -> Path:
    path = tmp_path / "project" / "agent_workflow" / "wf" / "agent_io"
    (path / "store").mkdir(parents=True)
    return path


@pytest.fixture
def released(monkeypatch) -> list[str]:
    calls: list[str] = []

    def release(batch_id: str) -> bool:
        calls.append(batch_id)
        return True

    monkeypatch.setattr(local_batch_records, "release_local_batch_record", release)
    monkeypatch.setattr(local_batch_records, "discard_partial_batch_records", lambda: None)
    return calls


def _store_naming(io_dir: Path, batch_id: str) -> Path:
    """Make the store of the current mode, with a registry that names *batch_id*."""
    backend = get_storage_backend(workflow_path=str(io_dir.parent), workflow_name="wf")
    backend.initialize()
    try:
        entry = {
            "batch_id": batch_id,
            "status": "completed",
            "timestamp": "t",
            "provider": "agac-provider",
        }
        backend.save_metadata("batch_registry:summarize", json.dumps({"pages.json": entry}))
    finally:
        backend.close()
    return store_file(io_dir, "wf")


def _of_another_format(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE workflow_metadata SET value = '3' WHERE key = 'storage_format_version'")
    conn.commit()
    conn.close()


def _cleaner(io_dir: Path) -> Cleaner:
    manager = MagicMock()
    manager.get_agent_paths.return_value = ("", str(io_dir), "")
    return Cleaner(agent="wf", force=True, remove_all=True, agent_manager=manager)


def test_a_real_store_of_another_format_does_not_stop_the_sandbox_reclaim(io_dir, released):
    _of_another_format(_store_naming(io_dir, "real_batch"))
    with sandbox_mode(True):
        _store_naming(io_dir, "sandbox_batch")

    cleaner = _cleaner(io_dir)
    cleaner.run()

    assert released == ["sandbox_batch"]
    wiped = [call.args[1] for call in cleaner.agent_manager.clean_directory.call_args_list]
    assert io_dir / "store" in wiped


def test_a_sandbox_store_of_another_format_does_not_stop_the_real_reclaim(io_dir, released):
    _store_naming(io_dir, "real_batch")
    with sandbox_mode(True):
        _of_another_format(_store_naming(io_dir, "sandbox_batch"))

    _cleaner(io_dir).run()

    assert released == ["real_batch"]


def test_the_reclaim_creates_no_real_store(io_dir, released):
    with sandbox_mode(True):
        _store_naming(io_dir, "sandbox_batch")

    assert _cleaner(io_dir)._release_batch_records(io_dir) is True

    assert released == ["sandbox_batch"]
    assert not (io_dir / "store" / "wf.db").exists()

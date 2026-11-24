"""The docs catalog names a workflow by its real store, never by the store of a sandbox run."""

from __future__ import annotations

from pathlib import Path

from agent_actions.config.sandbox import sandbox_mode, store_file
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.tooling.docs.scanner.data_scanners import scan_workflow_data


def _store(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backend = SQLiteBackend(str(db_path), "review")
    backend.initialize()
    try:
        backend._write_target_raw("classify", "data.json", [{"source_guid": "g1"}])
        backend.write_source("data.json", [{"source_guid": "g1"}])
    finally:
        backend.close()


def test_a_sandbox_store_is_not_a_workflow(tmp_path):
    io_dir = tmp_path / "agent_workflow" / "review" / "agent_io"
    _store(store_file(io_dir, "review"))
    with sandbox_mode(True):
        _store(store_file(io_dir, "review"))

    assert sorted(scan_workflow_data(tmp_path)) == ["review"]


def test_a_workflow_with_only_a_sandbox_store_is_not_listed(tmp_path):
    io_dir = tmp_path / "agent_workflow" / "review" / "agent_io"
    with sandbox_mode(True):
        _store(store_file(io_dir, "review"))

    assert scan_workflow_data(tmp_path) == {}

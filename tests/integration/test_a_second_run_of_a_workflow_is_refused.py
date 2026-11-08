"""A run or retry of a workflow is refused while another process holds that workflow."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import portalocker
import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def {name}_echo(data: Any, *args) -> list[dict]:
    return [{"got": repr(data)}]
"""


def _workflow(root: Path, name: str) -> None:
    directory = root / "agent_workflow" / name
    (directory / "agent_config").mkdir(parents=True)
    staging = directory / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (staging / "rows.json").write_text(json.dumps([{"title": "a"}]))
    (root / "tools" / name).mkdir(parents=True)
    (root / "tools" / name / f"{name}_tools.py").write_text(TOOLS.replace("{name}", name))
    (directory / "agent_config" / f"{name}.yml").write_text(
        f"""name: {name}
description: "One tool action"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: echo
    kind: tool
    intent: "Echo"
    impl: {name}_echo
    schema: {{ got: string }}
    context_scope: {{ observe: [source.*] }}
"""
    )


def _project(base: Path, *names: str) -> Path:
    root = base / "project"
    root.mkdir()
    (root / "agent_actions.yml").write_text(
        'tool_path: ["tools"]\nschema_path: schema\n'
        "default_agent_config:\n  model_name: gpt-4o-mini\n"
    )
    (root / "schema").mkdir()
    for name in names or ("one_run",):
        _workflow(root, name)
    return root


@contextmanager
def _held(root: Path, name: str, pid: str = "48211") -> Iterator[None]:
    """Hold *name*'s run lock from this process, as a run in progress would."""
    path = root / "agent_workflow" / name / "agent_io" / "store" / f"{name}.db.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(path, mode="a+", flags=portalocker.LOCK_EX | portalocker.LOCK_NB) as f:
        f.seek(0)
        f.truncate()
        f.write(pid)
        f.flush()
        yield


def _agac(root: Path, *args: str):
    return run_agac(root, *args, env={"OPENAI_API_KEY": "sk-not-used"})


def _stored(root: Path, name: str) -> list[dict]:
    db = root / "agent_workflow" / name / "agent_io" / "store" / f"{name}.db"
    if not db.exists():
        return []
    try:
        rows = stored_rows(db, "select data from target_data where action_name = 'echo'")
    except sqlite3.OperationalError:
        return []
    return [record for (data,) in rows for record in json.loads(data)]


def _output(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def test_a_run_is_refused_while_another_holds_the_workflow(tmp_path):
    root = _project(tmp_path)

    with _held(root, "one_run"):
        result = _agac(root, "run", "-a", "one_run", "--fresh")

    output = _output(result)
    assert result.returncode == 1, output
    assert (
        "RunInProgressError: Another run of workflow 'one_run' is in progress (pid 48211). "
        "Wait for it to finish or stop it, then run again." in output
    ), output
    assert "--fresh: cleared stored results" not in output, output
    assert _stored(root, "one_run") == [], output


def test_a_retry_is_refused_while_another_holds_the_workflow(tmp_path):
    root = _project(tmp_path)
    first = _agac(root, "run", "-a", "one_run")
    assert first.returncode == 0, _output(first)

    with _held(root, "one_run"):
        result = _agac(root, "retry", "-a", "one_run")

    output = _output(result)
    assert result.returncode == 1, output
    assert "Another run of workflow 'one_run' is in progress (pid 48211)" in output, output


def test_a_pid_the_lock_file_does_not_hold_is_left_out_of_the_refusal(tmp_path):
    root = _project(tmp_path)

    with _held(root, "one_run", pid=""):
        result = _agac(root, "run", "-a", "one_run")

    output = _output(result)
    assert result.returncode == 1, output
    assert "Another run of workflow 'one_run' is in progress. Wait for it" in output, output


def test_a_read_is_not_refused(tmp_path):
    root = _project(tmp_path)
    first = _agac(root, "run", "-a", "one_run")
    assert first.returncode == 0, _output(first)

    with _held(root, "one_run"):
        reads = [
            _agac(root, "records", "-w", "one_run"),
            _agac(root, "retry", "-a", "one_run", "--dry-run"),
            _agac(root, "inspect", "-a", "one_run"),
            _agac(root, "status", "-a", "one_run"),
        ]

    for read in reads:
        assert read.returncode == 0, _output(read)
        assert "in progress" not in _output(read), _output(read)


def test_a_run_proceeds_once_the_lock_is_released(tmp_path):
    root = _project(tmp_path)
    with _held(root, "one_run"):
        pass

    result = _agac(root, "run", "-a", "one_run")

    assert result.returncode == 0, _output(result)
    assert len(_stored(root, "one_run")) == 1, _output(result)


def test_another_workflow_is_not_blocked(tmp_path):
    root = _project(tmp_path, "one_run", "other_run")

    with _held(root, "one_run"):
        result = _agac(root, "run", "-a", "other_run")

    assert result.returncode == 0, _output(result)
    assert len(_stored(root, "other_run")) == 1, _output(result)


def test_a_filter_is_refused_while_another_holds_the_workflow(tmp_path):
    """`--filter` writes dispositions, rows, the status file and the manifest (1698)."""
    root = _project(tmp_path)
    first = _agac(root, "run", "-a", "one_run")
    assert first.returncode == 0, _output(first)

    with _held(root, "one_run"):
        result = _agac(
            root, "retry", "-a", "one_run", "--filter", "echo:some-record", "--reason", "known bad"
        )

    output = _output(result)
    assert result.returncode == 1, output
    assert "Another run of workflow 'one_run' is in progress (pid 48211)" in output, output
    assert "Nothing was filtered" not in output, output


def test_a_filter_dry_run_is_not_refused(tmp_path):
    root = _project(tmp_path)
    first = _agac(root, "run", "-a", "one_run")
    assert first.returncode == 0, _output(first)

    with _held(root, "one_run"):
        result = _agac(
            root,
            "retry",
            "-a",
            "one_run",
            "--filter",
            "echo:some-record",
            "--reason",
            "known bad",
            "--dry-run",
        )

    # It writes nothing, so it reads past the lock and answers for the record.
    output = _output(result)
    assert "in progress" not in output, output
    assert "Nothing was filtered" in output, output


@pytest.mark.parametrize("flags", [[], ["--target"], ["--all"]], ids=["source", "target", "all"])
def test_a_clean_is_refused_while_another_holds_the_workflow(tmp_path, flags):
    """`clean` deletes what a run reads and writes, `--all` the lock file with it (1699)."""
    root = _project(tmp_path)
    first = _agac(root, "run", "-a", "one_run")
    assert first.returncode == 0, _output(first)
    io_dir = root / "agent_workflow" / "one_run" / "agent_io"
    for sub in ("source", "target"):
        (io_dir / sub / "echo").mkdir(parents=True, exist_ok=True)
        (io_dir / sub / "echo" / "kept.json").write_text("[]")

    with _held(root, "one_run"):
        result = _agac(root, "clean", "-a", "one_run", "--force", *flags)

    output = _output(result)
    assert result.returncode == 1, output
    assert "Another run of workflow 'one_run' is in progress (pid 48211)" in output, output
    assert (io_dir / "store" / "one_run.db.lock").exists(), output
    assert (io_dir / "staging" / "rows.json").exists(), output
    assert (io_dir / "source" / "echo" / "kept.json").exists(), output
    assert (io_dir / "target" / "echo" / "kept.json").exists(), output
    assert len(_stored(root, "one_run")) == 1, output


def test_a_clean_runs_once_no_run_holds_the_workflow(tmp_path):
    root = _project(tmp_path)
    first = _agac(root, "run", "-a", "one_run")
    assert first.returncode == 0, _output(first)

    result = _agac(root, "clean", "-a", "one_run", "--force", "--all")

    assert result.returncode == 0, _output(result)
    store = root / "agent_workflow" / "one_run" / "agent_io" / "store"
    # Only the run lock file stays, held through the delete.
    assert [p.name for p in store.iterdir()] == ["one_run.db.lock"]

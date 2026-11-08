"""A run holds its workflow's lock for the whole run, and a refused run leaves the store as it was."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import portalocker

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

WORKFLOW = "lock_probe"

# The tool tries the workflow's lock from inside the run, on a handle of its own.
TOOLS = """import os
from typing import Any

import portalocker

from agent_actions import udf_tool


@udf_tool
def lock_probe_check(data: Any, *args) -> list[dict]:
    if os.environ.get("LOCK_PROBE_FAIL"):
        raise RuntimeError("failed on purpose, for the retry")
    try:
        with open(os.environ["LOCK_PROBE_PATH"], "a+") as handle:
            portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
            portalocker.unlock(handle)
    except portalocker.LockException:
        return [{"held": True}]
    return [{"held": False}]
"""


def _project(base: Path) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    staging = directory / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (staging / "rows.json").write_text(json.dumps([{"title": "a"}]))
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "lock_probe_tools.py").write_text(TOOLS)
    (root / "schema").mkdir()
    (root / "agent_actions.yml").write_text(
        'tool_path: ["tools"]\nschema_path: schema\n'
        "default_agent_config:\n  model_name: gpt-4o-mini\n"
    )
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "One tool action that reports whether the run lock is held"
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
  - name: check
    kind: tool
    intent: "Report whether the run lock is held"
    impl: lock_probe_check
    schema: {{ held: boolean }}
    context_scope: {{ observe: [source.*] }}
"""
    )
    return root


def _lock_path(root: Path) -> Path:
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db.lock"


def _agac(root: Path, *args: str, fail: bool = False):
    env = {"OPENAI_API_KEY": "sk-not-used", "LOCK_PROBE_PATH": str(_lock_path(root))}
    if fail:
        env["LOCK_PROBE_FAIL"] = "1"
    return run_agac(root, *args, env=env)


def _held_values(root: Path) -> list[bool]:
    db = root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"
    try:
        rows = stored_rows(db, "select data from target_data where action_name = 'check'")
    except sqlite3.OperationalError:
        return []
    return [r["content"]["check"]["held"] for (data,) in rows for r in json.loads(data)]


def _output(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def test_the_lock_is_held_while_the_run_executes_and_free_after_it(tmp_path):
    root = _project(tmp_path)

    result = _agac(root, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _held_values(root) == [True], _output(result)
    with portalocker.Lock(
        _lock_path(root), mode="a+", flags=portalocker.LOCK_EX | portalocker.LOCK_NB
    ):
        pass


def test_a_refused_fresh_run_leaves_the_stored_rows_in_place(tmp_path):
    root = _project(tmp_path)
    first = _agac(root, "run", "-a", WORKFLOW)
    assert first.returncode == 0, _output(first)
    assert _held_values(root) == [True], _output(first)

    with portalocker.Lock(
        _lock_path(root), mode="a+", flags=portalocker.LOCK_EX | portalocker.LOCK_NB
    ):
        refused = _agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert refused.returncode == 1, _output(refused)
    assert "is in progress" in _output(refused), _output(refused)
    assert _held_values(root) == [True], _output(refused)


def test_the_lock_is_held_while_a_retry_executes(tmp_path):
    root = _project(tmp_path)
    _agac(root, "run", "-a", WORKFLOW, fail=True)
    assert _held_values(root) == []

    result = _agac(root, "retry", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _held_values(root) == [True], _output(result)

"""`agac retry --all` goes on while a pass closes an open failure, even when as many open.

A pass that repairs the failures of an action re-runs the action below it for the same
records, and they can fail there. The count of open failures is then what it was, but
the failures are not the same ones: one more pass repairs them. `--all` measured only
the count, stopped after the first pass and exited 3.

Two tool actions in a chain, `a -> b`. Pages 1 and 2 fail one time at `a`, then one time
at `b`. Each command is its own `agac` process.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_RECORD_FAILURES, EXIT_SUCCESS
from tests._support.agac_cli import run_agac

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "retry_all_chain"
PAGES = ("Page 1.", "Page 2.", "Page 3.")
FAIL_ONCE = (("a", "Page 1."), ("a", "Page 2."), ("b", "Page 1."), ("b", "Page 2."))

_CONFIG = f"""\
name: {WORKFLOW}
description: "Two tool actions in a chain"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: a
    kind: tool
    intent: "First"
    schema: tool_action_output
    impl: chain_a
    context_scope: {{ observe: [source.page_content] }}
    expect: {{ repair: none }}
  - name: b
    kind: tool
    dependencies: [a]
    intent: "Second"
    schema: tool_action_output
    impl: chain_b
    context_scope: {{ observe: [a.summary] }}
    expect: {{ repair: none }}
"""

# A file under fail_once/<action>/ names a page that action fails one time: the tool
# removes the file as it raises.
_TOOLS = """\
from pathlib import Path
from typing import Any

from agent_actions import udf_tool

HERE = Path(__file__).resolve().parents[2]


def _text(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("page_content", "summary"):
            if key in data:
                return str(data[key])
        for value in data.values():
            found = _text(value)
            if found:
                return found
    return ""


def _fail_once(action: str, text: str) -> None:
    for flag in sorted((HERE / "fail_once" / action).glob("*")):
        page = flag.read_text()
        if page in text:
            flag.unlink()
            raise RuntimeError(f"{page} fails one time at {action}")


@udf_tool
def chain_a(data: Any, *args) -> list[dict]:
    page = _text(data)
    _fail_once("a", page)
    return [{"summary": page, "exam_density": "low"}]


@udf_tool
def chain_b(data: Any, *args) -> list[dict]:
    summary = _text(data)
    _fail_once("b", summary)
    return [{"summary": f"B[{summary}]", "exam_density": "low"}]
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def _agac(root: Path, *args: str) -> tuple[int, str]:
    result = run_agac(root, *args)
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def _open_failures(root: Path) -> dict[str, int]:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select action_name, count(*) from record_disposition"
            " where disposition in ('failed', 'exhausted') group by action_name"
        )
        return dict(rows)
    finally:
        con.close()


@pytest.fixture
def project(tmp_path) -> Path:
    """A run that left pages 1 and 2 failed at `a`, with one failure each still due at `b`."""
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_CONFIG)
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        "[" + ", ".join(f'{{"page_content": "{page}"}}' for page in PAGES) + "]"
    )
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "chain_tools.py").write_text(_TOOLS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    for n, (action, page) in enumerate(FAIL_ONCE):
        flag = root / "fail_once" / action / str(n)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(page)

    code, output = _agac(root, "run", "-w", WORKFLOW, "--fresh")
    assert code == EXIT_RECORD_FAILURES, output
    assert _open_failures(root) == {"a": 2}, output
    return root


def test_one_retry_all_repairs_failures_that_moved_to_the_next_action(project):
    code, output = _agac(project, "retry", "-w", WORKFLOW, "--all")

    assert _open_failures(project) == {}, output
    assert code == EXIT_SUCCESS, output
    assert "Pass 1: 2 open failure(s) left" in output, output
    assert "Pass 2: 0 open failure(s) left" in output, output
    assert not [flag for flag in (project / "fail_once").rglob("*") if flag.is_file()]

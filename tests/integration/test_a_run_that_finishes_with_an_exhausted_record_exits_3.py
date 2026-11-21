"""A run that finishes holding a failed or exhausted record exits 3, not 0.

The action that holds the record completed, so the workflow finished, and `agac run`
exited 0: a CI job could not tell it from a clean run. Every run is an `agac run`
through the CLI against a stub server that answers one record with 429 until its
retries are spent.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests._support.fake_endpoint import FakeEndpoint

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "exit_code_probe"
MAX_ATTEMPTS = 2
RECORD_FAILURES = 3

SCHEMA = """name: classify
fields:
  - id: label
    type: string
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


@pytest.fixture
def provider() -> Iterator[FakeEndpoint]:
    with FakeEndpoint() as endpoint:
        endpoint.sdk_retries = False
        yield endpoint


def _project(base: Path, pages: int) -> Path:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    project_file = root / "agent_actions.yml"
    project_file.write_text(
        project_file.read_text() + "\nendpoints:\n  lab:\n    url: ${LAB_URL}\n    auth: none\n"
    )
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "classify.yml").write_text(SCHEMA)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "One action on a declared endpoint"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: lab
  model_name: local-7b
  retry: {{ enabled: true, max_attempts: {MAX_ATTEMPTS}, base_delay: 0.01 }}
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: classify
    intent: "Classify"
    schema: classify
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""
    )
    rows = [{"page_id": f"p{i}", "page_content": f"Page {i}."} for i in range(pages)]
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(rows))
    return root


def _run(root: Path, provider: FakeEndpoint, *args: str) -> tuple[int, str]:
    result = run_agac(root, "run", "-a", WORKFLOW, *args, env={"LAB_URL": provider.base_url})
    return result.returncode, result.stdout + result.stderr


def _dispositions(root: Path) -> list[str]:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition"
            " where action_name = 'classify' and record_id != '__node__'"
        )
        return sorted(row[0] for row in rows)
    finally:
        con.close()


def test_a_run_with_one_exhausted_record_exits_3(tmp_path, provider):
    root = _project(tmp_path, pages=3)
    provider.statuses = [200, *[429] * MAX_ATTEMPTS, 200]

    code, output = _run(root, provider, "--fresh")

    assert _dispositions(root) == ["exhausted", "success", "success"], output
    assert code == RECORD_FAILURES, output
    assert "failed or exhausted records in: classify" in output, output
    assert f"agac dispositions -w {WORKFLOW} --quarantined" in output, output
    assert f"agac retry -w {WORKFLOW}." in output, output


def test_the_same_run_with_every_record_answered_exits_0(tmp_path, provider):
    root = _project(tmp_path, pages=3)

    code, output = _run(root, provider, "--fresh")

    assert _dispositions(root) == ["success", "success", "success"], output
    assert code == 0, output


def test_a_second_run_over_the_exhausted_record_still_exits_3(tmp_path, provider):
    """Nothing repaired the record, so the workflow still holds it."""
    root = _project(tmp_path, pages=3)
    provider.statuses = [200, *[429] * MAX_ATTEMPTS, 200]
    _run(root, provider, "--fresh")

    code, output = _run(root, provider)

    assert code == RECORD_FAILURES, output


def test_a_retry_that_repairs_the_record_exits_0(tmp_path, provider):
    root = _project(tmp_path, pages=3)
    provider.statuses = [200, *[429] * MAX_ATTEMPTS, 200]
    _run(root, provider, "--fresh")

    result = run_agac(root, "retry", "-a", WORKFLOW, env={"LAB_URL": provider.base_url})

    assert result.returncode == 0, result.stdout + result.stderr
    assert _dispositions(root) == ["success", "success", "success"]


def test_a_retry_that_leaves_the_record_exhausted_exits_3(tmp_path, provider):
    root = _project(tmp_path, pages=3)
    provider.statuses = [200, *[429] * MAX_ATTEMPTS, 200]
    _run(root, provider, "--fresh")
    provider.statuses = [429] * MAX_ATTEMPTS

    result = run_agac(root, "retry", "-a", WORKFLOW, env={"LAB_URL": provider.base_url})

    output = result.stdout + result.stderr
    assert result.returncode == RECORD_FAILURES, output
    assert _dispositions(root) == ["exhausted", "success", "success"], output
    assert "Retry complete." not in output

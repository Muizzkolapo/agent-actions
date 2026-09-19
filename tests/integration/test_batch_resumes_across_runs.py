"""A batch workflow spans two processes, so its provider state has to as well.

Submitting a batch pauses the run and asks to be run again. The second run is a
new process. A provider that keeps what it submitted in memory has forgotten it
by then, and the workflow can never collect what it sent — which no single-process
test can see, because the state is still there.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    for config in root.glob("agent_workflow/*/agent_config/*.yml"):
        config.write_text(
            config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
        )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\nOPENAI_API_KEY=sk-not-used\n")
    return root


def _run(project, *args):
    """One `agac run`, in its own process — the boundary under test.

    The mock completes a batch after a delay, which is a separate question from
    whether it still knows about one. Set to zero so a paused run is a run that
    lost its batch, not one that asked too early.
    """
    result = subprocess.run(
        [str(Path(sys.executable).parent / "agac"), "run", "-a", WORKFLOW, "-u", "tools", *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    return result.returncode, result.stdout + result.stderr


def _records(project):
    store = project / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    dbs = sorted(store.glob("*.db")) if store.is_dir() else []
    if not dbs:
        return []
    con = sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True)
    try:
        blobs = [row[0] for row in con.execute("select data from target_data")]
    finally:
        con.close()
    out = []
    for blob in blobs:
        loaded = json.loads(blob)
        out.extend(loaded if isinstance(loaded, list) else [loaded])
    return out


class TestASubmittedBatchIsCollectableByTheNextRun:
    def test_the_second_run_does_not_report_an_unknown_batch(self, project):
        """The symptom: the provider is asked about a batch it no longer holds,
        and answers with a status the framework has no handling for."""
        assert _run(project, "--fresh")[0] == 0

        _, output = _run(project)

        assert "Unrecognized batch status" not in output, output

    def test_the_workflow_completes(self, project):
        """Two runs is the contract a paused batch states: submit, then collect."""
        first_code, first = _run(project, "--fresh")
        assert first_code == 0, first
        assert "run again" in first, "the fixture did not pause on submission"

        code, output = _run(project)

        assert code == 0, output
        assert "paused" not in output, output

    def test_it_produces_the_records_it_submitted(self, project):
        assert _run(project, "--fresh")[0] == 0
        _run(project)

        assert _records(project), "the batch was submitted but nothing was ever collected"

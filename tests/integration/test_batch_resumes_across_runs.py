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


def _run(project, *args, env=None):
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
        env={**os.environ, "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", **(env or {})},
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

    def test_a_poll_counts_towards_the_next_run(self, project):
        """`polls_until_complete` counts status checks across runs.

        Submitting does not poll, so the count runs from the second run on: with
        a threshold of two, the second run reaches one and the third reaches two.
        A count that restarted each run would sit at one forever.
        """
        env = {"AGAC_BATCH_POLLS_UNTIL_COMPLETE": "2", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "999"}
        assert _run(project, "--fresh", env=env)[0] == 0
        second_code, second = _run(project, env=env)
        assert second_code == 0, second
        assert "paused" in second, "a threshold of two cannot be met by one poll"

        code, output = _run(project, env=env)

        assert code == 0, output
        assert "paused" not in output, output

    def test_it_produces_the_records_it_submitted(self, project):
        assert _run(project, "--fresh")[0] == 0
        _run(project)

        assert _records(project), "the batch was submitted but nothing was ever collected"


class TestTheRecordIsFoundFromAnywhereInTheProject:
    """`agac` supports being run from a subdirectory and does not chdir, so a
    location derived from the working directory would lose the batch exactly as
    this exists to prevent."""

    def test_a_different_working_directory_finds_the_same_batch(self, project, monkeypatch):
        from agent_actions.config.paths import PathManager
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
        from agent_actions.utils.path_utils import set_path_manager

        set_path_manager(PathManager(project_root=project))
        submitted = AgacBatchClient()._state_dir()

        # a second run standing somewhere else in the same project
        monkeypatch.chdir(project / "agent_workflow")
        set_path_manager(PathManager(project_root=project))

        assert AgacBatchClient()._state_dir() == submitted

    def test_the_record_does_not_sit_where_a_workflow_would_be_looked_for(self, project):
        """`agent_io/` marks a workflow to the docs scanner, which keys a run by
        the directory above it. A copy at the project root would report a
        workflow named after the project."""
        from agent_actions.config.paths import PathManager
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
        from agent_actions.utils.path_utils import set_path_manager

        set_path_manager(PathManager(project_root=project))

        assert "agent_io" not in AgacBatchClient()._state_dir().parts


class TestARecordThatSaysNothingAboutABatch:
    """A batch id with no readable record is unknown, which is what lets the
    caller report it. Raising from a status check instead would end the run."""

    @pytest.fixture
    def client(self, project):
        from agent_actions.config.paths import PathManager
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
        from agent_actions.utils.path_utils import set_path_manager

        set_path_manager(PathManager(project_root=project))
        AgacBatchClient._batches.clear()
        AgacBatchClient._tasks_by_batch.clear()
        return AgacBatchClient()

    @pytest.mark.parametrize(
        "content",
        ['{"batch_id": "b"}', "{}", "not json at all", '{"batch_id": "b", "status": 1}[', ""],
        ids=["missing-fields", "empty-object", "not-json", "truncated", "empty-file"],
    )
    def test_it_reports_unknown_rather_than_raising(self, client, content):
        (client._state_dir() / "b.json").write_text(content)

        assert client._fetch_status("b") == "unknown"

    def test_a_batch_never_submitted_is_unknown(self, client):
        assert client._fetch_status("mock_batch_never_existed") == "unknown"


class TestTwoBatchesInFlight:
    def test_each_is_recorded_under_its_own_id(self, project):
        from agent_actions.config.paths import PathManager
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState
        from agent_actions.utils.path_utils import set_path_manager

        set_path_manager(PathManager(project_root=project))
        client = AgacBatchClient()
        for batch_id, task in (("mock_a", {"custom_id": "a"}), ("mock_b", {"custom_id": "b"})):
            client._write_state(MockBatchState(batch_id=batch_id), [task])

        AgacBatchClient._batches.clear()
        AgacBatchClient._tasks_by_batch.clear()

        assert AgacBatchClient._load_state("mock_a") is not None
        assert AgacBatchClient._load_state("mock_b") is not None
        assert AgacBatchClient._tasks_by_batch["mock_a"] == [{"custom_id": "a"}]
        assert AgacBatchClient._tasks_by_batch["mock_b"] == [{"custom_id": "b"}]

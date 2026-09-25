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


def _run_workflow(project, workflow, *args, env=None):
    """One `agac run`, in its own process — the boundary under test.

    The mock completes a batch after a delay, which is a separate question from
    whether it still knows about one. Set to zero so a paused run is a run that
    lost its batch, not one that asked too early.
    """
    result = subprocess.run(
        [str(Path(sys.executable).parent / "agac"), "run", "-a", workflow, "-u", "tools", *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", **(env or {})},
    )
    return result.returncode, result.stdout + result.stderr


def _run(project, *args, env=None):
    return _run_workflow(project, WORKFLOW, *args, env=env)


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


@pytest.fixture
def scoped_to(project):
    """Point the framework at this project, and put back what was there.

    `set_path_manager` installs a global. A test that leaves its own behind
    sends every later test's writes wherever this project was — which is how
    three batch records ended up at the repo root while this was being built.
    """
    from agent_actions.config.paths import PathManager
    from agent_actions.utils import path_utils

    previous = path_utils._global_path_manager
    path_utils.set_path_manager(PathManager(project_root=project))
    yield project
    path_utils._global_path_manager = previous


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

    def test_a_different_working_directory_finds_the_same_batch(self, scoped_to, monkeypatch):
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

        submitted = AgacBatchClient()._state_dir()

        # a second run standing somewhere else in the same project
        monkeypatch.chdir(scoped_to / "agent_workflow")

        assert AgacBatchClient()._state_dir() == submitted

    def test_the_record_does_not_sit_where_a_workflow_would_be_looked_for(self, scoped_to):
        """`agent_io/` marks a workflow to the docs scanner, which keys a run by
        the directory above it. A copy at the project root would report a
        workflow named after the project."""
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

        assert "agent_io" not in AgacBatchClient()._state_dir().parts


class TestARecordThatSaysNothingAboutABatch:
    """A batch id with no readable record is unknown, which is what lets the
    caller report it. Raising from a status check instead would end the run."""

    @pytest.fixture
    def client(self, scoped_to):
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

        AgacBatchClient._batches.clear()
        AgacBatchClient._tasks_by_batch.clear()
        # The state directory is made by a submit, not by being asked for.
        AgacBatchClient._state_dir().mkdir(parents=True, exist_ok=True)
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
    def test_each_is_recorded_under_its_own_id(self, scoped_to):
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState

        client = AgacBatchClient()
        for batch_id, task in (("mock_a", {"custom_id": "a"}), ("mock_b", {"custom_id": "b"})):
            client._write_state(MockBatchState(batch_id=batch_id), [task])

        AgacBatchClient._batches.clear()
        AgacBatchClient._tasks_by_batch.clear()

        assert AgacBatchClient._load_state("mock_a") is not None
        assert AgacBatchClient._load_state("mock_b") is not None
        assert AgacBatchClient._tasks_by_batch["mock_a"] == [{"custom_id": "a"}]
        assert AgacBatchClient._tasks_by_batch["mock_b"] == [{"custom_id": "b"}]


class TestTheRecordOutlivesTheRead:
    """Reading results hands bytes to a caller that still has to write, parse,
    reconcile and evaluate them. Any of that can fail with the batch already
    marked done, and the next run comes back for the same batch — so the record
    cannot be spent by the read."""

    @pytest.fixture
    def submitted(self, scoped_to):
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState

        client = AgacBatchClient()
        client._write_state(
            MockBatchState(batch_id="b1", status="completed"),
            [{"custom_id": "x", "schema": None}],
        )
        return client

    @staticmethod
    def _as_a_new_process():
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

        AgacBatchClient._batches.clear()
        AgacBatchClient._tasks_by_batch.clear()

    def test_a_second_run_can_still_collect_it(self, submitted):
        self._as_a_new_process()
        submitted._fetch_raw_results("b1")

        self._as_a_new_process()

        assert submitted._fetch_raw_results("b1"), "the read spent the record"

    def test_it_is_still_reported_as_a_batch_afterwards(self, submitted):
        self._as_a_new_process()
        submitted._fetch_raw_results("b1")

        self._as_a_new_process()

        assert submitted._fetch_status("b1") != "unknown"


class TestTheRecordHasAnEndOfLife:
    """A record holds the batch's whole payload — every prompt and every piece of
    user content it was submitted with — and today nothing ever ends its life.

    It dies with the registry entry that names it. Not earlier: while an entry
    names a batch the framework can still be sent back to it, and a spent record
    turns that into `Batch not found`.
    """

    @staticmethod
    def _on_disk(project):
        state = project / ".agac" / "batch_state"
        return sorted(p.name for p in state.glob("*")) if state.is_dir() else []

    def test_an_abandoned_batch_is_reclaimed_by_a_fresh_run(self, project):
        """A batch nobody ever collects is what --fresh means by a clean slate."""
        assert _run(project, "--fresh")[0] == 0
        abandoned = set(self._on_disk(project))
        assert abandoned, "the submit recorded nothing to reclaim"

        assert _run(project, "--fresh")[0] == 0

        assert not abandoned & set(self._on_disk(project))

    def test_a_collected_batch_is_reclaimed_by_a_fresh_run(self, project):
        """--fresh drops the registry too, so nothing can be sent back to it."""
        assert _run(project, "--fresh")[0] == 0
        assert _run(project)[0] == 0
        collected = set(self._on_disk(project))
        assert collected, "the cycle recorded nothing to reclaim"

        assert _run(project, "--fresh")[0] == 0

        assert not collected & set(self._on_disk(project))

    def test_a_neighbours_fresh_run_does_not_take_this_batch(self, project):
        """One `.agac/batch_state` serves the whole project; --fresh is per
        workflow. A neighbour's clean slate must leave this batch collectable."""
        assert _run(project, "--fresh")[0] == 0
        in_flight = set(self._on_disk(project))
        assert in_flight, "the submit recorded nothing"

        code, output = _run_workflow(project, "inline_rules", "--fresh")
        assert code == 0, output

        assert in_flight <= set(self._on_disk(project))
        assert _run(project)[0] == 0
        assert _records(project), "the batch was no longer collectable"

    def test_clean_all_reclaims_the_records_it_would_orphan(self, project):
        """`agac clean --all` wipes the store holding the registry. Afterwards no
        entry names these batches, so nothing could ever find them to reclaim."""
        assert _run(project, "--fresh")[0] == 0
        assert self._on_disk(project), "the submit recorded nothing"

        cleaned = subprocess.run(
            [str(Path(sys.executable).parent / "agac"), "clean", "-a", WORKFLOW, "--all", "-f"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr

        assert self._on_disk(project) == []

    def test_asking_where_records_live_creates_nothing(self, scoped_to):
        """A project that never submitted a batch must not gain a `.agac/` for
        having been asked where one would go — which is what --fresh does now."""
        from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

        assert not (scoped_to / ".agac").exists()

        AgacBatchClient()._state_dir()

        assert not (scoped_to / ".agac").exists()

    def test_a_fresh_run_discards_a_half_written_record(self, project):
        """`atomic_json_write` mkstemps beside the target, so a kill between
        create and rename leaves a `.tmp` holding the same payload — and one
        written before the registry entry was saved is named by nothing, so
        only a sweep can reach it. Backdated because a write in progress owns
        its temp file and a sweep has to leave that one alone."""
        assert _run(project, "--fresh")[0] == 0
        orphan = project / ".agac" / "batch_state" / "mock_batch_abandoned_kj38fa.tmp"
        orphan.write_text('{"tasks": [{"user_content": "secret"}]}')
        os.utime(orphan, (1700000000, 1700000000))

        assert _run(project, "--fresh")[0] == 0

        assert not orphan.exists()

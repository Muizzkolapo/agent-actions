"""Runtime failure behaviour, driven through the real CLI.

These probes came from a real project, where they existed as throwaway workflows
for watching failure handling live. What they watch cannot be seen from a unit
test: the staging guard, the exit code, the run summary and the durable status
are produced by four different layers, and only an end-to-end run puts them
together.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "runtime_probes"

RESERVED_REMEDY = "Rename the colliding field(s) in your staging data"


@dataclass
class Run:
    workflow: str
    project: Path
    returncode: int
    output: str

    @property
    def flat(self) -> str:
        """The output on one line, since the run summary wraps long messages."""
        return " ".join(self.output.split())

    @property
    def records(self) -> list[dict]:
        """Every record persisted to the store, flattened. Empty if no store exists."""
        store = self.project / "agent_workflow" / self.workflow / "agent_io" / "store"
        dbs = list(store.glob("*.db")) if store.is_dir() else []
        if not dbs:
            return []
        blobs = [row[0] for row in stored_rows(dbs[0], "select data from target_data")]
        out: list[dict] = []
        for blob in blobs:
            loaded = json.loads(blob)
            out.extend(loaded if isinstance(loaded, list) else [loaded])
        return out

    def status(self, action: str) -> str:
        path = self.project / "agent_workflow" / self.workflow / "agent_io" / ".agent_status.json"
        return json.loads(path.read_text())[action]["status"]


@pytest.fixture
def run(tmp_path):
    def _run(workflow: str) -> Run:
        project = tmp_path / workflow
        shutil.copytree(FIXTURE, project)
        (project / ".env").write_text("OPENAI_API_KEY=sk-not-used\nOLLAMA_API_KEY=not-used\n")
        result = run_agac(project, "run", "-a", workflow, "--fresh")
        return Run(workflow, project, result.returncode, result.stdout + result.stderr)

    return _run


class TestReservedNamespaceCollision:
    """A staging field named `source` shadows the prompt-context namespace."""

    def test_the_run_fails_and_names_the_field_and_the_remedy(self, run):
        r = run("staging_namespace_collision")

        assert r.returncode != 0, f"expected a failing run, got 0\n{r.output}"
        assert "'source'" in r.flat
        assert "collide with reserved namespace names" in r.flat
        assert RESERVED_REMEDY in r.flat

    def test_the_rejected_file_persists_nothing(self, run):
        assert run("staging_namespace_collision").records == []


class TestPartialFileRejection:
    """One staging file is rejected, so the whole first stage is: nothing of the clean file runs."""

    def test_the_rejection_is_reported(self, run):
        r = run("partial_file_rejection")

        assert "b_reserved.json" in r.flat
        assert "collide with reserved namespace names" in r.flat

    def test_no_file_produces_a_record(self, run):
        assert run("partial_file_rejection").records == []

    def test_the_run_fails_and_the_action_is_not_completed(self, run):
        r = run("partial_file_rejection")

        assert r.returncode != 0, r.output
        assert r.status("label_page") != "completed"


class TestEveryStagedFileIsCheckedFirst:
    """A row no seed file covers in the second file stops the run before the first is sent."""

    def test_the_run_names_the_file_and_the_record(self, run):
        r = run("staging_precheck")

        assert r.returncode != 0, r.output
        assert (
            "record value 'snowflak' for 'source.exam' is not in the file map. "
            "Known values: dbt, snowflake. (staging/b_uncovered.json, record 1)"
        ) in r.flat

    def test_nothing_of_the_clean_file_is_stored(self, run):
        r = run("staging_precheck")

        assert r.records == []
        assert r.status("label_page") != "completed"


class TestRepairExhaustion:
    """A repair loop whose rule can never be satisfied."""

    def test_the_record_survives_exhaustion_carrying_its_last_verdict(self, run):
        r = run("repair_exhaustion")
        assert r.returncode == 0, r.output

        records = r.records
        assert len(records) == 1, "on_exhausted: return_last must keep the record"

        verdict = records[0]["content"]["summarize"]["expect"]
        assert verdict["overall_pass"] is False
        assert verdict["failed"] == ["density_is_a_known_bucket"]

        outcomes = {o["id"]: o for o in verdict["outcomes"]}
        assert outcomes["density_is_a_known_bucket"]["passed"] is False
        assert outcomes["reason_is_present"]["passed"] is True
        assert outcomes["density_is_a_known_bucket"]["detail"], "a failure must say why"

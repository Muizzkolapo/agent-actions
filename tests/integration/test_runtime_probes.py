"""Runtime failure behaviour, driven through the real CLI.

These probes came from a real project, where they existed as throwaway workflows
for watching failure handling live. What they watch cannot be seen from a unit
test: the staging guard, the exit code, the run summary and the durable status
are produced by four different layers, and only an end-to-end run puts them
together.
"""

import json
import re
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


def _summary_cells(output: str, action: str) -> dict[str, str]:
    """One action's row of `agac dispositions`, keyed by its column header."""
    header = next(line for line in output.splitlines() if line.startswith("┃"))
    names = [cell.strip() for cell in header.strip("┃").split("┃")]
    row = next(
        line
        for line in output.splitlines()
        if line.startswith("│") and line.strip("│").split("│")[0].strip() == action
    )
    return dict(zip(names, (cell.strip() for cell in row.strip("│").split("│")), strict=True))


def _action_complete_data(r: Run) -> dict[str, dict]:
    events = r.project / "agent_workflow" / r.workflow / "agent_io" / "logs" / "events.json"
    rows = [json.loads(line) for line in events.read_text().splitlines() if line.strip()]
    return {
        row["data"]["action_name"]: row["data"]
        for row in rows
        if row.get("event_type") == "ActionCompleteEvent"
    }


class TestHonestyProbe:
    """The run line and `agac dispositions` say what the records did, guard skips apart."""

    def test_honesty_probe_names_guard_skips(self, run):
        r = run("honesty_probe")
        assert r.returncode == 0, r.output

        line = next(row for row in r.output.splitlines() if " repaired  " in row)
        assert "repaired  4 records in" in line
        assert line.rstrip().endswith("— 1 skipped by guard")
        for action in ("observed", "warned"):
            other = next(row for row in r.output.splitlines() if f" {action}  " in row)
            assert "skipped by guard" not in other

        assert _action_complete_data(r)["repaired"]["guard_skipped"] == 1
        assert _action_complete_data(r)["observed"]["guard_skipped"] == 0

    def test_honesty_probe_traces_every_attempt(self, run):
        r = run("honesty_probe")
        assert r.returncode == 0, r.output

        (db,) = (r.project / "agent_workflow" / "honesty_probe" / "agent_io" / "store").glob("*.db")
        rows = stored_rows(
            db,
            "select record_id, attempt, compiled_prompt, response_text from prompt_trace "
            "where action_name = 'repaired' order by record_id, attempt",
        )
        by_record: dict[str, list[int]] = {}
        for record_id, attempt, _, _ in rows:
            by_record.setdefault(record_id, []).append(attempt)
        assert len(rows) == 9
        assert sorted(by_record.values()) == [[0, 1, 2]] * 3
        for _, attempt, prompt, response in rows:
            assert response, f"attempt {attempt} has no response"
            repairing = "Regenerate the complete output" in prompt
            assert repairing is (attempt > 0), (attempt, prompt[-200:])

    @staticmethod
    def _project(tmp_path, run_mode="online"):
        project = tmp_path / "honesty_probe"
        shutil.copytree(FIXTURE, project)
        (project / ".env").write_text("OPENAI_API_KEY=sk-not-used\nOLLAMA_API_KEY=not-used\n")
        config = project / "agent_workflow" / "honesty_probe" / "agent_config" / "honesty_probe.yml"
        config.write_text(config.read_text().replace("run_mode: online", f"run_mode: {run_mode}"))
        return project

    @staticmethod
    def _repaired_line(output: str) -> str:
        """The completion line of `repaired`, unwrapped, up to the next completion icon."""
        flat = " ".join(output.split())
        (line,) = re.findall(r"✓ repaired \d+ records in [^✓]*", flat)
        return line

    def test_a_sequential_run_names_the_guard_skip_too(self, tmp_path):
        project = self._project(tmp_path)

        result = run_agac(
            project, "run", "-a", "honesty_probe", "--fresh", "--execution-mode", "sequential"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        line = self._repaired_line(result.stdout + result.stderr)
        assert "repaired 4 records in" in line
        assert "— 1 skipped by guard" in line

    def test_a_batch_run_names_the_guard_skip_on_the_run_that_completes_it(self, tmp_path):
        project = self._project(tmp_path, run_mode="batch")
        env = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}

        outputs = []
        result = run_agac(project, "run", "-a", "honesty_probe", "--fresh", env=env)
        outputs.append(result.stdout + result.stderr)
        for _ in range(5):
            if "run again" not in outputs[-1]:
                break
            result = run_agac(project, "run", "-a", "honesty_probe", env=env)
            outputs.append(result.stdout + result.stderr)

        assert result.returncode == 0, outputs[-1]
        completing = next(out for out in outputs if "✓ repaired" in " ".join(out.split()))
        line = self._repaired_line(completing)
        assert "repaired 4 records in" in line
        assert "— 1 skipped by guard" in line

    def test_dispositions_put_the_guard_skip_in_its_own_column(self, run):
        r = run("honesty_probe")
        assert r.returncode == 0, r.output

        shown = run_agac(r.project, "dispositions", "-a", "honesty_probe", env={"COLUMNS": "200"})
        assert shown.returncode == 0, shown.stdout + shown.stderr

        cells = _summary_cells(shown.stdout, "repaired")
        assert (cells["Failed checks"], cells["Guard skipped"], cells["Unprocessed"]) == (
            "3",
            "1",
            "0",
        )
        assert (cells["Success"], cells["Total"], cells["Records"]) == ("0", "4", "4")

    def test_honesty_probe_reports_failed_checks(self, run):
        r = run("honesty_probe")
        assert r.returncode == 0, r.output

        flat = r.flat
        assert "⚠ observed 4 records in" in flat
        assert "— 4 failed their checks" in flat
        assert "⚠ repaired 4 records in" in flat
        assert "— 1 skipped by guard, 3 failed their checks" in flat
        warned = re.findall(r"[✓⚠] warned 4 records in [^✓⚠]*", flat)
        assert warned and warned[0].startswith("✓") and "failed" not in warned[0]
        assert re.search(r"⚠ [0-9.]+s — 3 completed, 7 records failed their checks", flat)

    def test_honesty_probe_stores_failed_checks_as_successes(self, run):
        r = run("honesty_probe")
        assert r.returncode == 0, r.output

        (db,) = (r.project / "agent_workflow" / "honesty_probe" / "agent_io" / "store").glob("*.db")
        held = sorted(
            stored_rows(
                db,
                "select action_name, disposition, ifnull(reason, 'NULL'), count(*) "
                "from record_disposition where record_id != '__node__' group by 1, 2, 3",
            )
        )
        assert held == [
            ("observed", "success", "expectations_failed", 4),
            ("repaired", "success", "expectations_failed", 3),
            ("repaired", "unprocessed", "guard_skip", 1),
            ("warned", "success", "NULL", 4),
        ]

        shown = run_agac(r.project, "dispositions", "-a", "honesty_probe", env={"COLUMNS": "200"})
        observed = _summary_cells(shown.stdout, "observed")
        warned = _summary_cells(shown.stdout, "warned")
        assert (observed["Success"], observed["Failed checks"]) == ("0", "4")
        assert (warned["Success"], warned["Failed checks"]) == ("4", "0")

    def test_retry_finds_nothing_to_rerun_in_records_that_only_failed_their_checks(self, run):
        r = run("honesty_probe")
        assert r.returncode == 0, r.output

        dry = run_agac(r.project, "retry", "-a", "honesty_probe", "--dry-run")
        listed = dry.stdout + dry.stderr

        assert "observed" not in listed
        assert "repaired" not in listed

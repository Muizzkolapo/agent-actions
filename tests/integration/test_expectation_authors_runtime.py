"""The same seventeen authors, run by the CLI instead of asked about.

``test_expectation_authors.py`` puts each fixture through preflight and pins the
refusal message. That answers whether a block is *accepted*. It cannot answer
whether an accepted block then does what its author meant, because preflight
never runs the action.

So these drive ``agac run`` and read what reached the store. Preflight and
runtime have to agree on every fixture, and the verdict a rule reaches is pinned
by ``overall_pass`` and ``failed`` rather than by the outcome detail, which
embeds a generated value.

Offline: the vendor is swapped to the fake provider on the way in, so the suite
needs no credentials and no network.
"""

import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"

# Verdicts the fake provider produces. A rule with a closed vocabulary fails by
# construction against schema-shaped noise, and that failure is the end-to-end
# signal — not a defect in the fixture.
ACCEPTED: dict[str, dict[str, list[str]]] = {
    "custom_check": {"summarize": []},
    "field_scoped_rules": {"summarize": ["density_accepted_values"]},
    "inline_rules": {"summarize": ["density_is_known"]},
    "judge_votes_and_budget": {"summarize": []},
    "pair_and_pattern_rules": {"summarize": []},
    "record_expression": {"summarize": []},
    "repair_auto": {"summarize": ["density_is_known"]},
    "row_condition_on_optional_field": {"summarize": []},
    "shared_suite": {"summarize": ["density_is_known"], "resummarize": ["density_is_known"]},
    "tool_action": {"flatten": ["summary_present"]},
    "verdict_guard": {"summarize": ["density_is_known"]},
}

REFUSED = [
    "array_member_rule",
    "judged_context_under_batch",
    "many_mistakes",
    "old_flat_shape",
    "repair_auto_at_file_granularity",
]


@dataclass
class Run:
    workflow: str
    project: Path
    returncode: int
    output: str

    @property
    def store_exists(self) -> bool:
        """Whether a store was created at all — a refusal leaves no file, which a
        store that was created and then emptied would not satisfy."""
        return bool(self._dbs())

    @property
    def verdicts(self) -> dict[str, dict]:
        """The expect verdict each action wrote, keyed by action name."""
        out: dict[str, dict] = {}
        for db in self._dbs():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                blobs = [row[0] for row in con.execute("select data from target_data")]
            finally:
                con.close()
            for blob in blobs:
                loaded = json.loads(blob)
                for record in loaded if isinstance(loaded, list) else [loaded]:
                    if not isinstance(record, dict):
                        continue
                    for action, body in (record.get("content") or {}).items():
                        if isinstance(body, dict) and "expect" in body:
                            out[action] = body["expect"]
        return out

    def _dbs(self) -> list[str]:
        store = self.project / "agent_workflow" / self.workflow / "agent_io" / "store"
        return sorted(glob.glob(str(store / "*.db")))


@pytest.fixture(scope="session")
def run(tmp_path_factory):
    """One CLI run per workflow, shared across the assertions about it.

    Each fixture is asked several questions — did it write a verdict, which rules
    failed, does every failure say why — and re-running the workflow for each one
    would triple the suite's wall clock to answer questions about the same run.
    """
    done: dict[str, Run] = {}

    def _run(workflow: str, again: bool = False) -> Run:
        """*again* re-runs an already-run workflow in its own project, which a
        batch author needs: submitting pauses and the collect is a second run."""
        if workflow in done and not again:
            return done[workflow]
        project = done[workflow].project if again else tmp_path_factory.mktemp("authors") / workflow
        if not again:
            shutil.copytree(FIXTURE, project)
            # Only the vendor moves. The model name is carried through to the fake
            # provider, which ignores it, so leaving it alone keeps the fixtures
            # readable as the thing an author would have written.
            for config in project.glob("agent_workflow/*/agent_config/*.yml"):
                config.write_text(
                    config.read_text().replace(
                        "model_vendor: ollama_cloud", "model_vendor: agac-provider"
                    )
                )
            (project / ".env").write_text("OLLAMA_API_KEY=not-used\nOPENAI_API_KEY=sk-not-used\n")
        result = subprocess.run(
            [
                str(Path(sys.executable).parent / "agac"),
                "run",
                "-a",
                workflow,
                "-u",
                "tools",
                *([] if again else ["--fresh"]),
            ],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=300,
            # The fake batch provider completes after a delay by default; a
            # collect run that asked too early would look like a lost batch.
            env={**os.environ, "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
        )
        run_result = Run(workflow, project, result.returncode, result.stdout + result.stderr)
        if not again:
            # A resumed run must not replace the cached first one: a later test
            # asking for this workflow would silently get the collect run, and
            # the suite would depend on the order it happened to execute in.
            done[workflow] = run_result
        return run_result

    return _run


class TestAnAcceptedBlockReachesExecution:
    """Preflight accepting a block is a different claim from the action running."""

    @pytest.mark.parametrize("author", sorted(ACCEPTED))
    def test_every_action_writes_a_verdict(self, author, run):
        r = run(author)

        assert r.returncode == 0, r.output
        assert set(r.verdicts) == set(ACCEPTED[author]), r.output

    @pytest.mark.parametrize("author", sorted(ACCEPTED))
    def test_the_rules_that_failed_are_the_expected_ones(self, author, run):
        """`failed` is severity-filtered: an outcome with severity `warn` can
        report `passed: false` without appearing here."""
        verdicts = run(author).verdicts

        got = {action: verdict["failed"] for action, verdict in verdicts.items()}
        assert got == ACCEPTED[author]

    @pytest.mark.parametrize("author", sorted(ACCEPTED))
    def test_overall_pass_follows_from_what_failed(self, author, run):
        for action, verdict in run(author).verdicts.items():
            assert verdict["overall_pass"] is (not ACCEPTED[author][action]), action

    @pytest.mark.parametrize("author", sorted(ACCEPTED))
    def test_every_named_failure_says_why(self, author, run):
        """A failing outcome with no detail is a verdict no author can act on."""
        for action, verdict in run(author).verdicts.items():
            outcomes = {o["id"]: o for o in verdict["outcomes"]}
            for rule in ACCEPTED[author][action]:
                assert outcomes[rule]["passed"] is False, rule
                assert outcomes[rule]["detail"], rule


class TestARefusedBlockNeverRuns:
    """A refusal arriving late is a different defect from one arriving on time,
    and the exit status alone cannot tell them apart — several accepted fixtures
    also exit non-zero on a failing verdict."""

    @pytest.mark.parametrize("author", REFUSED)
    def test_it_is_refused_at_preflight(self, author, run):
        r = run(author)

        assert r.returncode != 0, r.output
        assert "PreFlightValidationError" in r.output, r.output

    @pytest.mark.parametrize("author", REFUSED)
    def test_it_persists_nothing(self, author, run):
        assert run(author).store_exists is False


class TestTheTwoSuitesAgree:
    """Where the CLI and the preflight suite disagree, the CLI is what an author
    runs, so the disagreement is the finding rather than a fixture to adjust."""

    def test_every_fixture_is_classified_exactly_once(self):
        from tests.integration.test_expectation_authors import ACCEPTED as PREFLIGHT_ACCEPTED
        from tests.integration.test_expectation_authors import REFUSED as PREFLIGHT_REFUSED

        on_disk = {p.name for p in (FIXTURE / "agent_workflow").iterdir() if p.is_dir()}
        here = set(ACCEPTED) | set(REFUSED) | {BATCH_ONLY}

        assert here == on_disk, "a fixture was added or removed without classifying it"
        assert set(REFUSED) == set(PREFLIGHT_REFUSED), "the two suites disagree on refusals"
        assert set(ACCEPTED) | {BATCH_ONLY} == set(PREFLIGHT_ACCEPTED), (
            "the two suites disagree on what preflight accepts"
        )


BATCH_ONLY = "batch_field_rules"


def test_the_batch_author_submits_and_is_collected(run):
    """The half this fixture can now prove: a batch survives the run boundary.

    Submitting pauses and asks to be run again; the second run collects it. That
    used to be impossible — the provider forgot the batch between processes — and
    this fixture was skipped for it.
    """
    first = run(BATCH_ONLY)
    assert first.returncode == 0, first.output
    assert "run again" in first.output, "the fixture did not pause on submission"

    second = run(BATCH_ONLY, again=True)

    assert second.returncode == 0, second.output
    assert "Unrecognized batch status" not in second.output, second.output
    assert set(second.verdicts) == {"summarize"}, second.output


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The batch path never produces the fields its schema declares: this "
        "provider writes a task flat with the schema at the top level, while the "
        "generator reads an OpenAI-shaped `body`, so it answers with its generic "
        "shape and every field rule fails on a field that is not there. A separate "
        "defect from the one this fixture was skipped for; asserted here so the "
        "gap stays visible rather than being pinned as the expected verdict."
    ),
)
def test_the_batch_author_reaches_a_verdict_on_its_own_fields(run):
    run(BATCH_ONLY)
    verdict = run(BATCH_ONLY, again=True).verdicts["summarize"]

    assert verdict["failed"] == []

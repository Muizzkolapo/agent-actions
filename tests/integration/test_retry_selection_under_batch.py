"""A repair under `run_mode: batch` submits and collects only what it named.

One claim per test, so a partial fix cannot hold the file green for a new
reason. The repair's own process must hand the provider its selection rather
than the prior batch's id; the separate collecting process must rebuild each
file from that narrow batch plus the rows it did not answer for, whatever
disposition those rows carry.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ACTION = "summarize"
RECORDS = 4


def _project(tmp_path):
    """A copy of the fixture project wired to the auto-completing provider mock."""
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    for config in root.glob("agent_workflow/*/agent_config/*.yml"):
        config.write_text(
            config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
        )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\nOPENAI_API_KEY=sk-not-used\n")
    return root


@pytest.fixture
def submitted_and_collected(tmp_path):
    """Four records through a full batch cycle: submitted, collected, merged."""
    root = _project(tmp_path)
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(RECORDS)])
    )

    _cycle(root, "run", "-a", WORKFLOW, "--fresh")
    assert len(_guids(root)) == RECORDS, "the fixture did not collect a row per staged record"
    return root


def _agac(project, *args):
    result = subprocess.run(
        [str(Path(sys.executable).parent / "agac"), *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    return result.returncode, result.stdout + result.stderr


def _cycle(project, *args):
    """Drive one command to completion: it submits and pauses, the next run collects."""
    transcript = []
    code, output = _agac(project, *args)
    assert code == 0, output
    transcript.append(output)
    while "run again" in transcript[-1]:
        assert len(transcript) <= RECORDS, "the batch never stopped asking to be run again"
        code, output = _agac(project, "run", "-a", WORKFLOW)
        assert code == 0, output
        transcript.append(output)
    return transcript


def _backend(project):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _dispositions(project):
    backend = _backend(project)
    try:
        return {r["record_id"]: r["disposition"] for r in backend.get_disposition(ACTION)}
    finally:
        backend.close()


def _guids(project):
    backend = _backend(project)
    try:
        return sorted(
            r["source_guid"]
            for path in backend.list_target_files(ACTION)
            for r in backend.read_target(ACTION, path)
            if r.get("source_guid")
        )
    finally:
        backend.close()


def _rows(project):
    """Each stored row whole, keyed by identity.

    Not the answer text: the provider mock regenerates content deterministically
    per `custom_id`, so a full replay reproduces it byte for byte and a content
    comparison cannot see the rewrite. The envelope can — `node_id`, `lineage` and
    `_state_history` are stamped per run. This is what the online counterpart,
    `test_named_retry_preserves_other_failure_and_output`, compares.
    """
    backend = _backend(project)
    try:
        return {
            r["source_guid"]: r
            for path in backend.list_target_files(ACTION)
            for r in backend._read_target_raw(ACTION, path)
            if r.get("source_guid")
        }
    finally:
        backend.close()


def _submitted_batches(project):
    """Every batch the provider mock holds, as {batch_id: task count}.

    A read never spends the record — only an entry that stops naming the batch
    does, which is a later moment and not every round reaches it. Callers
    therefore compare against a before-snapshot rather than reading a count.
    """
    state = project / ".agac" / "batch_state"
    if not state.is_dir():
        return {}
    return {
        f.stem: len(json.loads(f.read_text()).get("tasks") or [])
        for f in sorted(state.glob("*.json"))
    }


def _deferred_ids(project):
    """Real record identities of a submitted-but-uncollected batch.

    The fixture has no target rows yet, so `_guids` is empty there — the batch's
    records exist only as DEFERRED disposition rows.
    """
    backend = _backend(project)
    try:
        return sorted(
            r["record_id"] for r in backend.get_disposition(ACTION, disposition="deferred")
        )
    finally:
        backend.close()


def _set_disposition(project, record_id, disposition):
    backend = _backend(project)
    try:
        backend.set_disposition(ACTION, record_id, disposition, reason="constructed for this test")
    finally:
        backend.close()


@pytest.fixture
def two_files(tmp_path):
    """The same cycle over two staged files, two records each.

    A repair narrows its file walk to the files holding the records it named, so
    the second file is never re-submitted — and collection must not reach it
    either, however the prior cycle left the registry.
    """
    root = _project(tmp_path)
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    (staging / "pages.json").unlink()
    for name in ("a_pages.json", "b_pages.json"):
        staging.joinpath(name).write_text(
            json.dumps([{"page_id": f"{name}{i}", "page_content": f"{name} {i}"} for i in range(2)])
        )
    _cycle(root, "run", "-a", WORKFLOW, "--fresh")
    return root


def _guids_in(project, relative_path):
    backend = _backend(project)
    try:
        return [r["source_guid"] for r in backend.read_target(ACTION, relative_path)]
    finally:
        backend.close()


class TestTheRepairSubmitsWhatItNamed:
    def test_the_provider_is_asked_for_the_named_record(self, submitted_and_collected):
        """Asserted inside the repair's own process, before any collection: what
        the provider is handed is the selection, not the prior batch again."""
        project = submitted_and_collected
        before = _submitted_batches(project)
        selected = _guids(project)[0]
        _set_disposition(project, selected, "failed")

        code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", selected)
        assert code == 0, output

        added = {b: n for b, n in _submitted_batches(project).items() if b not in before}
        assert list(added.values()) == [1], (
            f"the repair named one record; the provider was handed {added}"
        )

    def test_the_named_record_is_repaired(self, submitted_and_collected):
        """The control: the repair does repair the named record, so the claims
        below are about what else it touches, not about the repair not running."""
        project = submitted_and_collected
        selected = _guids(project)[0]
        _set_disposition(project, selected, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert _dispositions(project)[selected] == "success"

    def test_no_record_is_added_or_lost(self, submitted_and_collected):
        """Asserted on identities, not the count: a lost row plus a backfilled one
        keeps the count and still means a record was lost."""
        project = submitted_and_collected
        before = _guids(project)
        selected = before[0]
        _set_disposition(project, selected, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert _guids(project) == before


class TestARecordTheRepairDidNotName:
    """One claim per test. Bundling the disposition and the row into one test
    lets a partial fix keep it red for an entirely different reason."""

    def test_an_exhausted_record_keeps_its_disposition(self, submitted_and_collected):
        """`exhausted` is terminal like `success`. Pinned online by
        `test_an_exhausted_record_is_not_erased_by_a_capped_retry`."""
        project = submitted_and_collected
        selected, unnamed = _guids(project)[0], _guids(project)[-1]
        _set_disposition(project, selected, "failed")
        _set_disposition(project, unnamed, "exhausted")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert _dispositions(project)[unnamed] == "exhausted"

    def test_a_failed_record_keeps_its_disposition(self, submitted_and_collected):
        """Two records failed and the repair names one — the shape
        `test_named_retry_preserves_other_failure_and_output` pins online."""
        project = submitted_and_collected
        selected, unnamed = _guids(project)[0], _guids(project)[-1]
        _set_disposition(project, selected, "failed")
        _set_disposition(project, unnamed, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert _dispositions(project)[unnamed] == "failed"

    def test_a_failed_record_still_has_a_row(self, submitted_and_collected):
        """Presence, asserted apart from content, because this is the half a
        narrowing fix gets wrong. Rebuilding the file from the records the batch
        answered for plus the *terminal* ones drops this row — `failed` is not in
        `TERMINAL_DISPOSITIONS` — leaving a disposition naming a record with no
        data.
        """
        project = submitted_and_collected
        selected, unnamed = _guids(project)[0], _guids(project)[-1]
        _set_disposition(project, selected, "failed")
        _set_disposition(project, unnamed, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert unnamed in _guids(project)

    def test_its_row_is_not_rewritten(self, submitted_and_collected):
        """Separate from the disposition claims above, and the half that catches a
        submission-only fix: a replay re-stamps the row even when the answer it
        carries comes back identical."""
        project = submitted_and_collected
        before = _rows(project)
        selected, unnamed = _guids(project)[0], _guids(project)[-1]
        _set_disposition(project, selected, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert _rows(project)[unnamed] == before[unnamed]


class TestAFileTheRepairNeverNamed:
    """Not an artifact of having one input file. The walk narrows to the files
    holding the named records, so a second file is never re-submitted — and
    collection must not reach it on the strength of the prior cycle's registry."""

    def test_it_keeps_its_dispositions(self, two_files):
        selected = _guids_in(two_files, "a_pages.json")[0]
        unnamed = _guids_in(two_files, "b_pages.json")[0]
        _set_disposition(two_files, selected, "failed")
        _set_disposition(two_files, unnamed, "exhausted")

        _cycle(two_files, "retry", "-a", WORKFLOW, "--record", selected)

        assert _dispositions(two_files)[unnamed] == "exhausted"

    def test_its_rows_are_not_rewritten(self, two_files):
        selected = _guids_in(two_files, "a_pages.json")[0]
        unnamed = _guids_in(two_files, "b_pages.json")[0]
        before = _rows(two_files)
        _set_disposition(two_files, selected, "failed")

        _cycle(two_files, "retry", "-a", WORKFLOW, "--record", selected)

        assert _rows(two_files)[unnamed] == before[unnamed]


class TestARepairArrivingWhileABatchIsInFlight:
    """A batch nobody has collected still owns its records.

    Letting a repair start here submits a second batch over the same file: two
    batches, each authoritative for a rewrite of it, and whichever is collected
    last wins. The first is paid for and its answers are thrown away. So the
    repair is refused, before it clears anything, and says how to proceed.
    """

    @pytest.fixture
    def submitted_not_collected(self, tmp_path):
        root = _project(tmp_path)
        staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"
        staging.write_text(
            json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(RECORDS)])
        )
        code, output = _agac(root, "run", "-a", WORKFLOW, "--fresh")
        assert code == 0, output
        assert "run again" in output, "the fixture collected the batch instead of pausing on it"
        return root

    def test_the_repair_is_refused(self, submitted_not_collected):
        project = submitted_not_collected
        _set_disposition(project, "p0", "failed")

        code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", "p0")

        assert code != 0, output
        assert "in flight" in output, output

    def test_the_refusal_leaves_the_disposition_alone(self, submitted_not_collected):
        """Refusing is only safe if it refuses before it clears. A repair that
        wiped the dispositions and then aborted would leave the record with no
        failure to find and no repair in progress."""
        project = submitted_not_collected
        _set_disposition(project, "p0", "failed")

        _agac(project, "retry", "-a", WORKFLOW, "--record", "p0")

        assert _dispositions(project)["p0"] == "failed"

    def test_a_dry_run_says_the_repair_would_be_refused(self, submitted_not_collected):
        """`--dry-run` is the documented way to see what a retry would do, so it is
        the one place the refusal has to appear before it costs anything. Reporting
        a plan the real command declines is the answer it must not give."""
        project = submitted_not_collected
        _set_disposition(project, "p0", "failed")

        code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", "p0", "--dry-run")

        assert "in flight" in output, output
        assert code == 0, "a dry run reports; it does not fail"

    def test_a_dry_run_still_changes_nothing(self, submitted_not_collected):
        """Surfacing the refusal must not cost the dry run its one guarantee."""
        project = submitted_not_collected
        _set_disposition(project, "p0", "failed")

        _agac(project, "retry", "-a", WORKFLOW, "--record", "p0", "--dry-run")

        assert _dispositions(project)["p0"] == "failed"

    def test_the_repair_can_be_let_through_deliberately(self, submitted_not_collected):
        """A batch the provider has forgotten — an expired id — leaves an entry that
        reads in flight forever, and every remedy the refusal names needs the
        provider to answer. The way out is explicit rather than absent.

        Named on a real identity of the abandoned batch, not a synthetic one: a
        record that matches no staged row is repaired by processing nothing, which
        a flag that merely exited 0 would satisfy just as well.
        """
        project = submitted_not_collected
        named = _deferred_ids(project)[0]
        _set_disposition(project, named, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", named, "--abandon-in-flight")

        assert _dispositions(project)[named] == "success"

    def test_the_rest_of_an_abandoned_batch_stays_reachable(self, submitted_not_collected):
        """The trap this flag would otherwise set. Its co-records are DEFERRED, and
        `deferred` is excluded from FAILURE_DISPOSITIONS because it means a batch is
        in flight that will resolve them. Abandoning ends the flight, not the wait —
        so unless they are moved, `agac retry` cannot see them, `agac run` is a
        no-op, and only `--fresh` recovers them: the loss this flag exists to avoid.
        """
        project = submitted_not_collected
        deferred = _deferred_ids(project)
        named, others = deferred[0], deferred[1:]
        assert others, "the fixture batch holds only one record; nothing to strand"
        _set_disposition(project, named, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", named, "--abandon-in-flight")

        after = _dispositions(project)
        assert [after[r] for r in others] == ["failed"] * len(others), (
            f"co-records of the abandoned batch are unreachable: { {r: after[r] for r in others} }"
        )

    def test_abandoning_names_what_it_gives_up(self, submitted_not_collected):
        """Abandoning is a loss, so it is reported rather than performed quietly."""
        project = submitted_not_collected
        _set_disposition(project, "p0", "failed")

        _code, output = _agac(
            project, "retry", "-a", WORKFLOW, "--record", "p0", "--abandon-in-flight"
        )

        assert "abandon" in output.lower(), output
        assert "batch_" in output, f"the batch id being given up is not named: {output}"
        assert "record" in output.lower(), (
            f"abandoning strands the batch's other records; the count is not reported: {output}"
        )

    def test_collecting_first_lets_the_repair_through(self, submitted_not_collected):
        """The refusal names a way forward, so the way forward has to work."""
        project = submitted_not_collected
        _cycle(project, "run", "-a", WORKFLOW)
        selected = _guids(project)[0]
        _set_disposition(project, selected, "failed")

        code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert code == 0, output

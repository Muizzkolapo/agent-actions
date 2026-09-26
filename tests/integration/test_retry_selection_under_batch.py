"""A repair under `run_mode: batch` does not narrow, and this is where that shows.

Two links, either alone enough. The repair's own process never submits:
`submit_batch_job` finds the prior COMPLETED registry entry and returns its id
above the gate, dropping the selection — yet the run still reports a pause, since
`managers/batch.py` only checks that some entry exists. Collection is then a
separate process, where `retried_records` is empty and which walks the registry
rather than the repair. The xfails carry one claim each, so a partial fix cannot
hold them red for a new reason.
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

# Strict, so a fix turns these into unexpected passes rather than quiet greens.
SUPPRESSED = pytest.mark.xfail(
    strict=True, reason="a completed registry entry suppresses the repair's own submission"
)
REPLAYED = pytest.mark.xfail(
    strict=True, reason="the collecting run replays the prior batch with an empty selection"
)


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
    the second file's registry entry is never replaced — and collection walks the
    registry, not the walk.
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
    @SUPPRESSED
    def test_the_provider_is_asked_for_the_named_record(self, submitted_and_collected):
        """Fails inside the repair's own process, before any collection: the
        completed entry short-circuits `submit_batch_job` and nothing is sent."""
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
        """The control: the replay does repair the named record, so the failures
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
    """One claim per test. Bundling the disposition and the row under one xfail
    lets a partial fix keep the test red for an entirely different reason."""

    @REPLAYED
    def test_an_exhausted_record_keeps_its_disposition(self, submitted_and_collected):
        """`exhausted` is terminal like `success`. Pinned online by
        `test_an_exhausted_record_is_not_erased_by_a_capped_retry`."""
        project = submitted_and_collected
        selected, unnamed = _guids(project)[0], _guids(project)[-1]
        _set_disposition(project, selected, "failed")
        _set_disposition(project, unnamed, "exhausted")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert _dispositions(project)[unnamed] == "exhausted"

    @REPLAYED
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
        data. Passes today only because the replay answers for everything.
        """
        project = submitted_and_collected
        selected, unnamed = _guids(project)[0], _guids(project)[-1]
        _set_disposition(project, selected, "failed")
        _set_disposition(project, unnamed, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert unnamed in _guids(project)

    @REPLAYED
    def test_its_row_is_not_rewritten(self, submitted_and_collected):
        """Separate from the disposition claims above, and the half that catches a
        submission-only fix: the row is re-stamped by the replay even when the
        answer it carries comes back identical."""
        project = submitted_and_collected
        before = _rows(project)
        selected, unnamed = _guids(project)[0], _guids(project)[-1]
        _set_disposition(project, selected, "failed")

        _cycle(project, "retry", "-a", WORKFLOW, "--record", selected)

        assert _rows(project)[unnamed] == before[unnamed]


class TestAFileTheRepairNeverNamed:
    """The defect is not an artifact of having one input file. The walk narrows to
    the files holding the named records, so a second file's registry entry is never
    replaced — and collection walks the registry, not the walk."""

    @REPLAYED
    def test_it_keeps_its_dispositions(self, two_files):
        selected = _guids_in(two_files, "a_pages.json")[0]
        unnamed = _guids_in(two_files, "b_pages.json")[0]
        _set_disposition(two_files, selected, "failed")
        _set_disposition(two_files, unnamed, "exhausted")

        _cycle(two_files, "retry", "-a", WORKFLOW, "--record", selected)

        assert _dispositions(two_files)[unnamed] == "exhausted"

    @REPLAYED
    def test_its_rows_are_not_rewritten(self, two_files):
        selected = _guids_in(two_files, "a_pages.json")[0]
        unnamed = _guids_in(two_files, "b_pages.json")[0]
        before = _rows(two_files)
        _set_disposition(two_files, selected, "failed")

        _cycle(two_files, "retry", "-a", WORKFLOW, "--record", selected)

        assert _rows(two_files)[unnamed] == before[unnamed]

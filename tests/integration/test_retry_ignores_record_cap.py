"""No limit that cuts by position may reach `agac retry`.

`record_limit`, `file_limit`, `AGAC_MAX_RECORDS` and `--max-records` all truncate
by position. A retry selects records by id, and it clears a record's disposition
before re-running — so a truncated retry does not merely skip the record it was
asked to repair, it erases the evidence that the record ever failed.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
ACTION = "flatten"
SECOND = "enrich"
RECORDS = 6

TAG_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def tag_density(data: Any, *args) -> list[dict]:
    return [{"summary": str((data or {}).get("summary", "")), "exam_density": "high"}]
"""

SECOND_ACTION = """  - name: enrich
    kind: tool
    dependencies: [flatten]
    intent: "Tag"
    schema: tool_action_output
    impl: tag_density
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A run of six records through a local tool — no network."""
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_content": f"page {i}"} for i in range(RECORDS)])
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return root


@pytest.fixture
def chained(project):
    """The same six records through two tool actions.

    The second action reads the first action's output rather than staging, so it
    runs the pipeline that a single-action workflow never reaches.
    """
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
    (project / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    assert _stored_records(project, SECOND) == RECORDS
    return project


def _backend(project):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _record_ids(project, action=ACTION):
    backend = _backend(project)
    try:
        rows = [r for r in backend.get_disposition(action) if r.get("record_id") != "__node__"]
        return [r["record_id"] for r in rows]
    finally:
        backend.close()


def _disposition(project, record_id, action=ACTION):
    backend = _backend(project)
    try:
        rows = [r for r in backend.get_disposition(action) if r.get("record_id") == record_id]
        return rows[0]["disposition"] if rows else None
    finally:
        backend.close()


def _fail(project, record_id, action=ACTION, disposition="failed"):
    backend = _backend(project)
    try:
        backend.set_disposition(action, record_id, disposition, reason="constructed for this test")
    finally:
        backend.close()


def _stored_records(project, action=ACTION):
    backend = _backend(project)
    try:
        return sum(len(backend.read_target(action, f)) for f in backend.list_target_files(action))
    finally:
        backend.close()


def _stored_guids(project, action=ACTION):
    backend = _backend(project)
    try:
        return sorted(
            r["source_guid"]
            for f in backend.list_target_files(action)
            for r in backend.read_target(action, f)
            if r.get("source_guid")
        )
    finally:
        backend.close()


def _a_record_the_cap_would_cut(project, cap, action=ACTION):
    """A record that sits past `cap` in the order the limit slices."""
    guids = [r["source_guid"] for r in _read_first_file(project, action)]
    assert len(guids) > cap, "fixture too small for this cap"
    return guids[-1]


def _read_first_file(project, action):
    backend = _backend(project)
    try:
        return backend.read_target(action, sorted(backend.list_target_files(action))[0])
    finally:
        backend.close()


class TestARecordNamedByIdIsAlwaysRetried:
    def test_a_late_record_is_repaired_under_a_cap(self, project, monkeypatch):
        """The cap would keep only the first record; this one is the last."""
        late = _a_record_the_cap_would_cut(project, cap=1)
        _fail(project, late)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert result.exit_code == 0, result.output
        assert _disposition(project, late) == "success"

    def test_the_failure_is_never_left_erased(self, project, monkeypatch):
        """Retry clears the disposition before re-running. If the record is then
        dropped, the failure is gone and nothing records that it happened."""
        late = _a_record_the_cap_would_cut(project, cap=1)
        _fail(project, late)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert _disposition(project, late) is not None, "the failure row was erased"

    def test_no_record_loses_its_disposition_row(self, project, monkeypatch):
        """Asserted on the ids, not the count: a lost row plus a spurious one
        keeps the count and still means a record was lost."""
        before = sorted(_record_ids(project))
        late = _a_record_the_cap_would_cut(project, cap=1)
        _fail(project, late)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert sorted(_record_ids(project)) == before


class TestABulkRetryIsNotTruncated:
    def test_every_failed_record_is_retried_under_a_cap(self, project, monkeypatch):
        ids = _record_ids(project)
        for record_id in ids[-3:]:
            _fail(project, record_id)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert [_disposition(project, r) for r in ids[-3:]] == ["success"] * 3


class TestEveryLimitIsDeclined:
    """The environment ceiling is only one of four ways to ask for a cut."""

    def test_a_configured_record_limit_does_not_truncate_a_retry(self, project):
        """`record_limit:` lives in the project's own config and slices through
        the same statement the environment ceiling does."""
        config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        config.write_text(
            config.read_text().replace(
                "  - name: flatten\n", "  - name: flatten\n    record_limit: 1\n"
            )
        )
        late = _a_record_the_cap_would_cut(project, cap=1)
        _fail(project, late)

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(project, late) == "success", "a configured limit truncated the retry"

    def test_a_file_limit_does_not_hide_the_file_a_record_lives_in(self, project):
        """`file_limit:` stops the run at N input files. A retried record lives
        in whichever file it lives in."""
        staging = project / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
        staging.joinpath("zz_extra.json").write_text(
            json.dumps([{"page_content": f"extra {i}"} for i in range(2)])
        )
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
        assert result.exit_code == 0, result.output

        backend = _backend(project)
        try:
            last_file = sorted(backend.list_target_files(ACTION))[-1]
            late = [r["source_guid"] for r in backend.read_target(ACTION, last_file)][-1]
        finally:
            backend.close()
        _fail(project, late)

        config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        config.write_text(
            config.read_text().replace(
                "  - name: flatten\n", "  - name: flatten\n    file_limit: 1\n"
            )
        )

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(project, late) == "success", "the file limit hid the record's file"


class TestEveryActionTheRetryRerunsDeclinesTheLimit:
    """A retry re-runs its starting action and everything below it. A limit left
    standing on any one of them cuts there instead."""

    def test_an_action_below_the_retry_point_is_not_truncated(self, chained, monkeypatch):
        before = _stored_guids(chained, SECOND)
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, ACTION)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _stored_guids(chained, SECOND) == before
        assert sorted(_record_ids(chained, SECOND)) == before


class TestOutputSurvivesTheRetry:
    """Dispositions say what a retry did; output rows say what it destroyed."""

    def test_every_action_keeps_its_rows(self, chained, monkeypatch):
        before = {a: _stored_guids(chained, a) for a in (ACTION, SECOND)}
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, SECOND)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, late, SECOND) == "success"
        assert {a: _stored_guids(chained, a) for a in (ACTION, SECOND)} == before

    def test_an_exhausted_record_keeps_its_output(self, chained, monkeypatch):
        """`exhausted` is terminal like `success`, so a retry that does not name
        it carries its prior output rather than rebuilding it."""
        before = _stored_guids(chained, SECOND)
        ids = _record_ids(chained, SECOND)
        _fail(chained, ids[0], SECOND, disposition="exhausted")
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, SECOND)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, ids[0], SECOND) == "exhausted"
        assert _stored_guids(chained, SECOND) == before


class TestRetryRepairsWhatWasTried:
    def test_a_failure_below_the_retry_point_is_still_repaired(self, chained):
        """The retry starts at the first action holding a failure. A record that
        failed further down is not named by it, and is still its to repair."""
        first = _record_ids(chained, ACTION)
        second = _record_ids(chained, SECOND)
        _fail(chained, first[-1], ACTION)
        _fail(chained, second[0], SECOND)

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, second[0], SECOND) == "success"
        assert _stored_records(chained, SECOND) == RECORDS

    def test_a_second_failure_keeps_its_row_when_one_record_is_named(self, chained):
        second = _record_ids(chained, SECOND)
        _fail(chained, second[-1], SECOND)
        _fail(chained, second[0], SECOND)

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", second[-1]])

        assert retry.exit_code == 0, retry.output
        assert _stored_records(chained, SECOND) == RECORDS
        assert _disposition(chained, second[0], SECOND) is not None

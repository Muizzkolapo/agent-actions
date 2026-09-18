"""A record cap must not reach `agac retry`.

A cap truncates by position; retry selects by identity. Applied to a retry, the
cap drops records the command was asked to repair — and because retry clears a
record's disposition before re-running, the failure is erased rather than fixed.
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
RECORDS = 6


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


class TestARecordNamedByIdIsAlwaysRetried:
    def test_a_late_record_is_repaired_under_a_cap(self, project, monkeypatch):
        """The cap would keep only the first record; this one is the last."""
        late = _record_ids(project)[-1]
        _fail(project, late)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert result.exit_code == 0, result.output
        assert _disposition(project, late) == "success"

    def test_the_failure_is_never_left_erased(self, project, monkeypatch):
        """Retry clears the disposition before re-running. If the record is then
        dropped, the failure is gone and nothing records that it happened."""
        late = _record_ids(project)[-1]
        _fail(project, late)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert _disposition(project, late) is not None, "the failure row was erased"

    def test_the_action_keeps_a_row_for_every_record(self, project, monkeypatch):
        """A retry may repair a record or leave it failed; it may not lose it.

        Asserted on the row count, because "nothing to retry" reads the same
        whether the record was repaired or its failure was erased.
        """
        before = len(_record_ids(project))
        late = _record_ids(project)[-1]
        _fail(project, late)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert len(_record_ids(project)) == before, "a record lost its disposition row"


class TestABulkRetryIsNotTruncated:
    def test_every_failed_record_is_retried_under_a_cap(self, project, monkeypatch):
        ids = _record_ids(project)
        for record_id in ids[-3:]:
            _fail(project, record_id)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert [_disposition(project, r) for r in ids[-3:]] == ["success"] * 3


def _stored_records(project, action=ACTION):
    backend = _backend(project)
    try:
        return sum(len(backend.read_target(action, f)) for f in backend.list_target_files(action))
    finally:
        backend.close()


class TestRetryTouchesOnlyWhatWasTried:
    """Retry repairs records that ran and failed. A record the cap kept out of
    the original run was never tried, so retry has no business processing it."""

    def test_records_never_tried_are_left_alone(self, project, monkeypatch):
        # A capped run tries two of the six staged records.
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--max-records", "2", "--fresh"])
        assert result.exit_code == 0, result.output
        assert _stored_records(project) == 2
        tried = _record_ids(project)
        assert len(tried) == 2
        _fail(project, tried[-1])

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", tried[-1]])

        assert retry.exit_code == 0, retry.output
        assert _disposition(project, tried[-1]) == "success"
        assert _stored_records(project) == 2, "retry processed records that were never tried"

    def test_a_configured_record_limit_does_not_truncate_a_retry(self, project, monkeypatch):
        """record_limit: lives in the project's own config and slices through the
        same statement the cap does, so it drops the record retry was given."""
        config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        config.write_text(
            config.read_text().replace(
                "  - name: flatten\n", "  - name: flatten\n    record_limit: 1\n"
            )
        )
        late = _record_ids(project)[-1]
        _fail(project, late)

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(project, late) == "success", "a configured limit truncated the retry"


SECOND = "enrich"

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
def chained(project):
    """The same six records through two tool actions.

    The second action reads the first action's output rather than staging, so
    it runs the pipeline that a single-action workflow never reaches.
    """
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
    (project / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    assert _stored_records(project, SECOND) == RECORDS
    return project


class TestACappedRetryKeepsEveryOutputRow:
    """Dispositions say what a retry did; output rows say what it destroyed.

    A record the retry does not name still has to come out the far end with the
    output it already had, at every action the retry re-runs.
    """

    def test_output_survives_at_every_action_the_retry_reruns(self, chained, monkeypatch):
        late = _record_ids(chained, SECOND)[-1]
        _fail(chained, late, SECOND)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, late, SECOND) == "success"
        assert _stored_records(chained, ACTION) == RECORDS
        assert _stored_records(chained, SECOND) == RECORDS

    def test_the_retried_record_keeps_its_own_output_row(self, chained, monkeypatch):
        """Row counts alone would pass if the named record vanished and an
        unnamed one were duplicated in its place."""
        late = _record_ids(chained, SECOND)[-1]
        _fail(chained, late, SECOND)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        backend = _backend(chained)
        try:
            stored = [
                r["source_guid"]
                for f in backend.list_target_files(SECOND)
                for r in backend.read_target(SECOND, f)
            ]
        finally:
            backend.close()
        assert sorted(stored) == sorted(_record_ids(chained, SECOND))

    def test_an_exhausted_record_is_carried_not_reprocessed(self, chained, monkeypatch):
        """`exhausted` is terminal like `success`, so a retry that does not name
        it must leave its output standing rather than drop it."""
        ids = _record_ids(chained, SECOND)
        _fail(chained, ids[0], SECOND, disposition="exhausted")
        _fail(chained, ids[-1], SECOND)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", ids[-1]])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, ids[0], SECOND) == "exhausted"
        assert _stored_records(chained, SECOND) == RECORDS

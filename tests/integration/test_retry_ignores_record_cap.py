"""A record limit may never cut loose a record `agac retry` is re-running.

A limit keeps the first N records by position; a retry selects records by id and
clears their dispositions before re-running. A limit that cuts one of them does
not merely skip it — it erases the evidence that the record ever failed.

So a limit admits the retried records on top of the N it already allows. It never
admits fewer: deciding how much *new* work to take on is what a limit is for, and
a retried record is work already taken on.
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
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    # A limit slices in staging order and the store keeps it. Pinned here so a
    # test asking for "a record past the cap" cannot quietly get one inside it.
    assert [r["content"]["source"]["page_content"] for r in _read_first_file(root, ACTION)] == [
        f"page {i}" for i in range(RECORDS)
    ]
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


def _guid_at(project, index, action=ACTION):
    """The guid at `index` in the order the limit slices."""
    return [r["source_guid"] for r in _read_first_file(project, action)][index]


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
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert result.exit_code == 0, result.output
        assert _disposition(project, late) == "success"

    def test_the_failure_is_never_left_erased(self, project, monkeypatch):
        """Retry clears the disposition before re-running. If the record is then
        dropped, the failure is gone and nothing records that it happened."""
        late = _a_record_the_cap_would_cut(project, cap=1)
        _fail(project, late)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert _disposition(project, late) is not None, "the failure row was erased"

    def test_no_record_loses_its_disposition_row(self, project, monkeypatch):
        """Asserted on the ids, not the count: a lost row plus a spurious one
        keeps the count and still means a record was lost."""
        before = sorted(_record_ids(project))
        late = _a_record_the_cap_would_cut(project, cap=1)
        _fail(project, late)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert sorted(_record_ids(project)) == before


class TestTheFirstRecordTheLimitExcludes:
    """Index == limit is the boundary. A range that starts one late admits every
    other retried record and silently drops this one."""

    def test_the_record_immediately_past_the_cap_is_repaired(self, project, monkeypatch):
        boundary = _guid_at(project, 1)
        _fail(project, boundary)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", boundary])

        assert result.exit_code == 0, result.output
        assert _disposition(project, boundary) == "success"


class TestABulkRetryIsNotTruncated:
    def test_every_failed_record_is_retried_under_a_cap(self, project, monkeypatch):
        ids = _record_ids(project)
        for record_id in ids[-3:]:
            _fail(project, record_id)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert [_disposition(project, r) for r in ids[-3:]] == ["success"] * 3


class TestAConfiguredLimitDoesNotCutARetriedRecord:
    def test_a_record_limit_does_not_truncate_a_retry(self, project):
        """`record_limit:` lives in the project's own config and slices through
        the same statement the environment limit does."""
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


class TestALimitOnlyEverAdmitsMore:
    """A limit that did not exclude the retried record must behave exactly as it
    does without a retry. Admitting the rest of the file would turn a one-record
    repair into a first-time backfill of everything the limit was holding back."""

    def test_a_limit_that_excludes_nothing_takes_on_no_extra_work(self, tmp_path, monkeypatch):
        root = tmp_path / "project"
        shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
        staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        staging.joinpath("pages.json").write_text(
            json.dumps([{"page_content": f"page {i}"} for i in range(RECORDS)])
        )
        config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        config.write_text(
            config.read_text().replace(
                "  - name: flatten\n", "  - name: flatten\n    record_limit: 2\n"
            )
        )
        monkeypatch.chdir(root)
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
        assert CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"]).exit_code == 0

        attempted = _record_ids(root)
        assert len(attempted) == 2, "the limit should have held the run to two records"
        _fail(root, attempted[-1])

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", attempted[-1]])

        assert retry.exit_code == 0, retry.output
        assert _disposition(root, attempted[-1]) == "success"
        assert sorted(_record_ids(root)) == sorted(attempted), "the retry backfilled new records"
        assert _stored_records(root) == 2


class TestEveryActionTheRetryRerunsAdmitsTheRecord:
    """A retry re-runs its starting action and everything below it. A limit left
    standing on any one of them cuts the record there instead."""

    def test_two_records_both_survive_the_action_below(self, chained, monkeypatch):
        """Two, not one. With a single record the action below can keep it by
        the luck of its input order, whether or not the limit was told about it.
        A cap of one cannot keep two by luck."""
        late = [_guid_at(chained, -2), _guid_at(chained, -1)]
        for guid in late:
            _fail(chained, guid, ACTION)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

        assert retry.exit_code == 0, retry.output
        assert [_disposition(chained, g, SECOND) for g in late] == ["success", "success"]
        assert [_disposition(chained, g, ACTION) for g in late] == ["success", "success"]

    def test_an_action_below_the_retry_point_still_gets_the_record(self, chained, monkeypatch):
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, ACTION)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, late, SECOND) == "success"
        assert late in _stored_guids(chained, SECOND)


class TestTheRetriedRecordKeepsItsOutput:
    """Dispositions say what a retry did; output rows say what it wrote."""

    def test_the_record_has_a_row_at_the_action_that_reran(self, chained, monkeypatch):
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, SECOND)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, late, SECOND) == "success"
        assert late in _stored_guids(chained, SECOND)

    def test_an_exhausted_record_is_not_erased_by_a_capped_retry(self, chained, monkeypatch):
        """`exhausted` is terminal like `success`. A retry that does not name it
        must not take its disposition away."""
        late = _a_record_the_cap_would_cut(chained, cap=1)
        other = next(r for r in _record_ids(chained, SECOND) if r != late)
        _fail(chained, other, SECOND, disposition="exhausted")
        _fail(chained, late, SECOND)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, other, SECOND) == "exhausted"


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


class TestARetryLeavesTheActionsAboveItAlone:
    """A retry is a record-set operation. A limit in force during one was not
    asked for by the retry, and must not reset a completed action above its
    starting point — that resets the action to pending, clears its dispositions
    and re-runs it truncated, destroying records the retry never named."""

    def test_an_upstream_action_keeps_every_record(self, chained, monkeypatch):
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, SECOND)
        before = set(_stored_guids(chained, ACTION))
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert set(_stored_guids(chained, ACTION)) == before

    def test_an_upstream_action_keeps_every_disposition(self, chained, monkeypatch):
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, SECOND)
        before = set(_record_ids(chained, ACTION))
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert set(_record_ids(chained, ACTION)) == before


class TestALimitDoesNotTruncateWhatARetryReruns:
    """A limit bounds how much *new* work a run takes on. A retry takes on none:
    every record at the actions it re-runs was already processed, and the target
    blob is rewritten whole, so a record dropped from processing loses its stored
    row. Bounding a repair therefore does not save work, it destroys output.
    """

    def test_the_action_the_retry_starts_from_keeps_every_row(self, chained, monkeypatch):
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, SECOND)
        before = set(_stored_guids(chained, SECOND))
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert set(_stored_guids(chained, SECOND)) == before

    def test_an_upstream_action_that_reruns_keeps_every_row(self, chained, monkeypatch):
        """An action above the retry point re-runs when its own config changed —
        correctly, its behaviour did change. It must not also be truncated."""
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, SECOND)
        before = set(_stored_guids(chained, ACTION))
        config = chained / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        config.write_text(
            config.read_text().replace(
                "    impl: flatten_pages\n",
                "    impl: flatten_pages\n"
                '    guard: { condition: \'source.page_content != ""\', on_false: "filter" }\n',
                1,
            )
        )
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert set(_stored_guids(chained, ACTION)) == before

    def test_the_retried_record_is_still_repaired(self, chained, monkeypatch):
        """The control: keeping every row must not come from the retry doing nothing."""
        late = _a_record_the_cap_would_cut(chained, cap=1)
        _fail(chained, late, SECOND)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", late])

        assert retry.exit_code == 0, retry.output
        assert _disposition(chained, late, SECOND) == "success"

"""An action completing for the first time during a repair stamps the limit it ran under.

A repair must not replace the stamp that says how much work an action
represents. That reasoning needs something stored to preserve, and a first
completion has nothing — so writing nothing records the same stamp a full
uncapped run writes, the cap cannot be told from no cap at all, and the action
is served as complete for ever on the records the repair named.
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
RECORDS = 8

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


def _backend(project):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _stamp(project, action):
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text()).get(action, {})


def _write_stamp(project, action, stamp):
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    status = json.loads(status_file.read_text())
    status[action] = stamp
    status_file.write_text(json.dumps(status))


def _stored_records(project, action):
    backend = _backend(project)
    try:
        return sum(len(backend.read_target(action, f)) for f in backend.list_target_files(action))
    finally:
        backend.close()


def _guids(project, action=ACTION):
    """Record ids in the order the limit slices them."""
    backend = _backend(project)
    try:
        first = sorted(backend.list_target_files(action))[0]
        return [r["source_guid"] for r in backend.read_target(action, first)]
    finally:
        backend.close()


def _fail(project, record_id, action=ACTION):
    backend = _backend(project)
    try:
        backend.set_disposition(action, record_id, "failed", reason="constructed for this test")
    finally:
        backend.close()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Eight records through one local tool action — no network, no limit."""
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
    assert _stored_records(root, ACTION) == RECORDS
    return root


@pytest.fixture
def repair_reaches_a_new_action(project):
    """A repair whose downstream reaches an action that has never completed.

    `agac retry` re-runs its starting action and everything below it, so an
    action added to the workflow after the last run is repaired without ever
    having completed. Asserted rather than assumed: the whole defect depends on
    this action having no stamp when the repair reaches it.
    """
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
    (project / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)
    assert _stamp(project, SECOND) == {}, "the second action must not have completed yet"
    _fail(project, _guids(project)[-1])
    return project


class TestAFirstCompletionRecordsTheCapItRanUnder:
    def test_the_limit_in_force_is_stamped(self, repair_reaches_a_new_action, monkeypatch):
        """`null` here is what a full uncapped run writes — the cap becomes unreadable."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        result = CliRunner().invoke(
            cli, ["retry", "-a", WORKFLOW, "--record", _guids(repair_reaches_a_new_action)[-1]]
        )

        assert result.exit_code == 0, result.output
        assert _stamp(repair_reaches_a_new_action, SECOND)["record_limit"] == 2

    def test_what_the_slice_admitted_is_left_unknown(
        self, repair_reaches_a_new_action, monkeypatch
    ):
        """The sibling key on the same guard is deliberately *not* filled in.

        The limit in force is a fact about the run whatever narrowed it
        afterwards, so it is stamped. These numbers are not: they come from the
        limit's own slice, and the repair narrows that slice again before
        anything is written — here to one row of eight. Stamping the slice would
        record `truncated: false` for an uncapped repair, and that is the one
        shape a later limit is allowed to read as proof it cannot truncate,
        turning a reopen into a skip."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        result = CliRunner().invoke(
            cli, ["retry", "-a", WORKFLOW, "--record", _guids(repair_reaches_a_new_action)[-1]]
        )

        assert result.exit_code == 0, result.output
        stamp = _stamp(repair_reaches_a_new_action, SECOND)
        assert stamp["records_processed"] is None
        assert stamp["truncated"] is None
        assert _stored_records(repair_reaches_a_new_action, SECOND) < 2, (
            "the run wrote fewer rows than the slice admitted — the reason these stay unknown"
        )

    def test_a_later_uncapped_run_no_longer_skips_the_action(
        self, repair_reaches_a_new_action, monkeypatch
    ):
        """The end state the stamp causes: one record of eight, served as complete."""
        project = repair_reaches_a_new_action
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")
        assert (
            CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", _guids(project)[-1]])
        ).exit_code == 0
        capped = _stored_records(project, SECOND)
        assert capped < RECORDS, "fixture failed to truncate the first completion"

        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert _stored_records(project, SECOND) == RECORDS


class TestARepairStillLeavesACompletedActionAlone:
    """The behaviour the guard was added for. A repair must not restate how much
    work an action represents — resetting a completed action on one clears its
    dispositions and re-runs it truncated."""

    def test_a_stored_limit_survives_a_repair_under_a_different_cap(self, project, monkeypatch):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "3")
        assert CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"]).exit_code == 0
        assert _stamp(project, ACTION)["record_limit"] == 3
        _fail(project, _guids(project)[0])

        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")
        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", _guids(project)[0]])

        assert result.exit_code == 0, result.output
        assert _stamp(project, ACTION)["record_limit"] == 3

    def test_a_stamp_using_the_retired_spelling_is_still_a_prior_completion(
        self, project, monkeypatch
    ):
        """`max_records` is what a run before the rename wrote, so such a stamp
        carries no `record_limit` key at all.

        It is still an earlier completion, and the repair must leave it alone.
        Deciding that per key instead — is `record_limit` stored? — reads this as
        an action that has never completed and writes the repair's own cap,
        which the next ordinary run reads as a change and re-runs truncated."""
        _write_stamp(
            project,
            ACTION,
            {"status": "completed", "max_records": 3, "config_hash": "written-before-the-rename"},
        )
        _fail(project, _guids(project)[0])
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", _guids(project)[0]])

        assert result.exit_code == 0, result.output
        assert _stamp(project, ACTION)["record_limit"] is None, (
            "the repair's own cap replaced a limit the action stored under the retired key"
        )


class TestAnUnlimitedFirstCompletionIsStillUnlimited:
    def test_no_cap_still_stamps_no_cap_and_is_still_skipped(
        self, repair_reaches_a_new_action, monkeypatch
    ):
        """`null` is the honest stamp when nothing was in force, and an action
        that processed everything must still be skipped by a later run."""
        project = repair_reaches_a_new_action
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
        assert (
            CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", _guids(project)[-1]])
        ).exit_code == 0
        assert _stamp(project, SECOND)["record_limit"] is None
        settled = _stored_records(project, SECOND)

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert _stored_records(project, SECOND) == settled


class TestAnUncappedRepairNeverVouchesForALaterLimit:
    """A repair narrows its own slice, so an uncapped one still writes fewer rows
    than the slice admitted. Recording that slice as untruncated would let a
    later limit above the count read the stamp as proof it cannot truncate."""

    def test_a_later_limit_above_the_input_still_reopens_the_action(
        self, repair_reaches_a_new_action, monkeypatch
    ):
        project = repair_reaches_a_new_action
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
        assert (
            CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", _guids(project)[-1]])
        ).exit_code == 0
        assert _stored_records(project, SECOND) < RECORDS

        monkeypatch.setenv("AGAC_RECORD_LIMIT", str(RECORDS + 2))
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert _stored_records(project, SECOND) == RECORDS

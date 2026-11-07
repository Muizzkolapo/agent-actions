"""A record a FILE tool cannot be handed is a failure of that action, counted and named.

Driven through `agac run`: the outcome lives in the stored dispositions, the action's
status and what the tool was handed, which no unit of the scope pass shows together.
"""

import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    RECORDS,
    WORKFLOW,
    _backend,
    _disposition,
    _record_ids,
    project,  # noqa: F401
)

PREPARE_TOOL = '''from typing import Any

from agent_actions import udf_tool


@udf_tool
def prepare_pages(data: Any, *args) -> list[dict]:
    """Emit region and zone for every page but one; raise for another when asked."""
    page = ((data or {}).get("source") or {}).get("page_content") or ""
    if page == "page 4" and __import__("os").environ.get("PREPARE_FAILS_PAGE_4") == "1":
        raise RuntimeError("page 4 cannot be prepared")
    out = {"summary": page, "exam_density": "low"}
    if page != "page 2":
        out["region"] = "north"
        out["zone"] = "z-north"
    return [out]
'''

COUNT_TOOL = '''from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool(granularity=Granularity.FILE)
def count_handed(data: Any, *args) -> Any:
    """Report, on every row, how many records the tool was handed."""
    return FileUDFResult(
        [
            {
                "source_index": i,
                "data": {"summary": f"{len(data)} handed", "exam_density": "low"},
            }
            for i, _ in enumerate(data or [])
        ]
    )
'''

ACTIONS = """  - name: prepare
    kind: tool
    dependencies: [flatten]
    intent: "Emit region and zone for every page but one"
    schema: tool_action_output
    impl: prepare_pages
    context_scope: { observe: [source.page_content, flatten.summary] }
    expect: { repair: none }
  - name: counted
    kind: tool
    granularity: File
    dependencies: [prepare]
    intent: "Count the records a FILE tool is handed"
    schema: tool_action_output
    impl: count_handed
    context_scope: { observe: [OBSERVE] }
    expect: { repair: none }
"""

MISSING_TWO = (
    "context_scope.observe fields 'prepare.region', 'prepare.zone' not found in this record"
)


def _declare(project, observe: str, guard: str | None = None):  # noqa: F811
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    actions = ACTIONS.replace("OBSERVE", observe)
    if guard:
        actions = actions.replace(
            "    impl: count_handed\n", f"    impl: count_handed\n    guard: {guard}\n"
        )
    config.write_text(config.read_text().rstrip("\n") + "\n" + actions)
    (project / "tools" / WORKFLOW / "refused_prepare.py").write_text(PREPARE_TOOL)
    (project / "tools" / WORKFLOW / "refused_count.py").write_text(COUNT_TOOL)


def _flat(output: str) -> str:
    """The run's output with the console's line wrapping folded away."""
    return " ".join(output.split())


def _status(project, action):  # noqa: F811
    path = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())[action]["status"]


def _reasons(project, action):  # noqa: F811
    backend = _backend(project)
    try:
        return {r["record_id"]: r.get("reason") for r in backend.get_disposition(action)}
    finally:
        backend.close()


def _rows(project, action):  # noqa: F811
    backend = _backend(project)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _page(project, n):  # noqa: F811
    """The record id of the staged page *n*, read from the first action's rows."""
    for row in _rows(project, "flatten"):
        if row["content"]["source"]["page_content"] == f"page {n}":
            return row["source_guid"]
    raise AssertionError(f"page {n} not found")


@pytest.fixture
def one_lacking_two(project):  # noqa: F811
    _declare(project, "prepare.summary, prepare.region, prepare.zone")
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return project, result


class TestOneRecordLacksTwoObservedFields:
    def test_that_record_fails_with_both_fields_named(self, one_lacking_two):
        project, _result = one_lacking_two  # noqa: F811
        page_2 = _page(project, 2)

        assert _disposition(project, page_2, "counted") == "failed"
        assert _reasons(project, "counted")[page_2] == MISSING_TWO

    def test_the_action_completes_with_failures_and_the_run_says_so(self, one_lacking_two):
        project, result = one_lacking_two  # noqa: F811

        assert _status(project, "counted") == "completed_with_failures"
        assert "completed with 1 item-level failure" in _flat(result.output)
        assert MISSING_TWO in _flat(result.output)
        assert "records skipped" not in _flat(result.output)

    def test_the_tool_was_handed_every_other_record(self, one_lacking_two):
        project, _result = one_lacking_two  # noqa: F811
        handed = {
            r["content"]["counted"]["summary"]
            for r in _rows(project, "counted")
            if r["content"].get("counted")
        }

        assert handed == {f"{RECORDS - 1} handed"}
        assert len(_record_ids(project, "counted")) == RECORDS


class TestEveryRecordLacksAField:
    def test_the_action_fails_and_no_guard_is_blamed(self, project):  # noqa: F811
        _declare(project, "prepare.summary, prepare.nope")

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code != 0
        assert _status(project, "counted") == "failed"
        assert "context_scope.observe field 'prepare.nope' not found in this record" in _flat(
            result.output
        )
        assert "guard-filtered" not in _flat(result.output)
        assert "guard" not in " ".join(str(v) for v in _reasons(project, "counted").values())


class TestARecordWhoseUpstreamFailedIsNotARefusal:
    def test_it_stays_unprocessed_and_the_action_is_not_failed_for_it(self, project, monkeypatch):  # noqa: F811
        """Control: an upstream failure is quarantined, not counted against this action."""
        monkeypatch.setenv("PREPARE_FAILS_PAGE_4", "1")
        _declare(project, "prepare.summary, prepare.exam_density")

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        page_4 = _page(project, 4)
        assert _disposition(project, page_4, "counted") == "unprocessed"
        assert _reasons(project, "counted")[page_4] == "upstream_unprocessed"
        assert _status(project, "counted") == "completed"


class TestAGuardCannotReadARefusedRecord:
    def test_a_record_lacking_an_observed_field_fails_even_under_a_guard_that_would_skip_it(
        self,
        project,  # noqa: F811
    ):
        """The guard's own context needs every observed field, so a record the scope
        refuses is failed before the guard, whatever the guard would have said."""
        _declare(
            project,
            "prepare.summary, prepare.region, prepare.zone",
            guard="{ condition: 'prepare.summary != \"page 2\"', on_false: skip }",
        )

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        page_2 = _page(project, 2)
        assert _disposition(project, page_2, "counted") == "failed"
        assert _reasons(project, "counted")[page_2] == MISSING_TWO
        assert _status(project, "counted") == "completed_with_failures"
        assert "guard" not in MISSING_TWO

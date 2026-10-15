"""A retry whose only stored row is its own failed row duplicates nothing and says so.

Below two actions that each split a record into several rows, a row carries the first
ancestor's identity, which is no input of the action under repair. The repair reported
every such row as unattributable and warned that regenerating the named record
"duplicates any it regenerates", although the named record's only stored row was its
own failed one, which the retry replaces.
"""

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    WORKFLOW,
    _backend,
    _fail,
    _record_ids,
    project,  # noqa: F401
)
from tests.integration.test_retry_of_an_expanding_action import (
    diamond,  # noqa: F401
    expanding,  # noqa: F401
)

SPLIT_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def split_pages(data: Any, *args) -> list[dict]:
    page = str(((data or {}).get("source") or {}).get("page_content", ""))
    return [{"summary": f"{page} #{half}", "exam_density": "high"} for half in (1, 2)]
"""

SPLIT_ACTION = """  - name: split
    kind: tool
    dependencies: [flatten]
    intent: "Split"
    schema: tool_action_output
    impl: split_pages
    context_scope: { observe: [flatten.summary, source.page_content] }
    expect: { repair: none }
"""

RESPLIT_TOOL = """import os
from typing import Any

from agent_actions import udf_tool


@udf_tool
def split_again(data: Any, *args) -> list[dict]:
    summary = str(((data or {}).get("split") or {}).get("summary", ""))
    if os.environ.get("RESPLIT_BREAKS_ON") == summary:
        raise RuntimeError("this input cannot be split")
    return [{"summary": f"{summary} .{part}", "exam_density": "low"} for part in ("x", "y")]
"""

RESPLIT_ACTION = """  - name: resplit
    kind: tool
    dependencies: [split]
    intent: "Split again"
    schema: tool_action_output
    impl: split_again
    context_scope: { observe: [split.summary] }
    expect: { repair: none }
"""

BREAKS_ON = "page 0 #1"


def _rows(project, action):  # noqa: F811
    backend = _backend(project)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend._read_target_raw(action, path)
        ]
    finally:
        backend.close()


@pytest.fixture
def two_splits(project, monkeypatch):  # noqa: F811
    """Six records through `split` (two rows each) and `resplit` (two rows per row),
    with one `split` row that `resplit` cannot split."""
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SPLIT_ACTION + RESPLIT_ACTION)
    (project / "tools" / WORKFLOW / "split_pages.py").write_text(SPLIT_TOOL)
    (project / "tools" / WORKFLOW / "resplit_pages.py").write_text(RESPLIT_TOOL)

    monkeypatch.setenv("RESPLIT_BREAKS_ON", BREAKS_ON)
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    monkeypatch.delenv("RESPLIT_BREAKS_ON")
    return project


def test_the_failed_row_is_the_only_one_that_did_not_split(two_splits):
    """The premise: 12 `split` rows, 11 of them split into two and one failed."""
    rows = _rows(two_splits, "resplit")

    assert len(rows) == (RECORDS * 2 - 1) * 2 + 1


def test_a_retry_of_the_failed_row_logs_no_unattributable_warning(two_splits):
    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert "cannot be attributed" not in result.output


def test_the_retry_replaces_the_failed_row_with_its_two_rows_and_nothing_grows(two_splits):
    CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

    assert len(_rows(two_splits, "resplit")) == RECORDS * 2 * 2


class TestAFanInOverARecordAndItsExpansion:
    """An action reading a record and an expansion over it once held the two side by
    side, so a row of the expansion's could not be told from the record's own and the
    retry warned it duplicated them. The fan-in now pairs each row of the expansion with
    the record (#1430): nothing stands beside its descendant, and nothing duplicates."""

    def test_the_retry_warns_of_no_duplicates(self, diamond):  # noqa: F811
        selected = _record_ids(diamond, ACTION)[0]
        _fail(diamond, selected, ACTION)

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

        assert result.exit_code == 0, result.output
        assert "cannot be attributed" not in result.output

    def test_it_cites_no_issue_number(self, diamond):  # noqa: F811
        selected = _record_ids(diamond, ACTION)[0]
        _fail(diamond, selected, ACTION)

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

        assert "issue #" not in result.output

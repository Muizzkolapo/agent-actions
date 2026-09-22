"""A retry below an action that mints an identity for every row it emits.

The identities a retry names are records; the rows such an action stores carry
none of them. The gate that hands untouched rows back to the rewrite compared
the two directly, so it handed back the rows the retry was regenerating and the
output grew every time.

Driven through the `agac retry` CLI rather than the processor, because every
caller narrows the input before the processor sees it — a harness that hands the
processor the whole list exercises a shape production never produces.
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

SPLIT_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def split_in_two(data: Any, *args) -> list[dict]:
    summary = str((data or {}).get("summary", ""))
    return [{"summary": f"{summary} #{half}", "exam_density": "high"} for half in (1, 2)]
"""

SPLIT_ACTION = """  - name: split
    kind: tool
    dependencies: [flatten]
    intent: "Split"
    schema: tool_action_output
    impl: split_in_two
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


@pytest.fixture
def expanding(project):  # noqa: F811
    """The six records through a second action that turns each into two rows.

    More rows out than records in, which is what makes it an expansion: every
    row is minted a fresh identity and none carries its record's.
    """
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SPLIT_ACTION)
    (project / "tools" / WORKFLOW / "split.py").write_text(SPLIT_TOOL)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return project


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


def test_the_fixture_really_mints(expanding):
    """The premise, asserted: two rows per record, and no row carries a record's
    identity. Without this the rest could pass against a one-to-one action."""
    rows = _rows(expanding, "split")
    assert len(rows) == RECORDS * 2
    assert {r["source_guid"] for r in rows}.isdisjoint(set(_record_ids(expanding, ACTION)))
    assert all(r.get("parent_source_guid") for r in rows)


def test_a_retry_does_not_grow_the_stored_output(expanding):
    selected = _record_ids(expanding, ACTION)[0]
    _fail(expanding, selected, ACTION)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert result.exit_code == 0, result.output
    assert len(_rows(expanding, "split")) == RECORDS * 2


def test_the_rows_of_the_retried_record_are_replaced_not_added(expanding):
    selected = _record_ids(expanding, ACTION)[0]
    stale = {
        r["source_guid"] for r in _rows(expanding, "split") if r["parent_source_guid"] == selected
    }
    assert len(stale) == 2
    _fail(expanding, selected, ACTION)

    CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert stale.isdisjoint({r["source_guid"] for r in _rows(expanding, "split")})


def test_the_rows_of_every_other_record_survive_untouched(expanding):
    selected = _record_ids(expanding, ACTION)[0]
    others = {
        r["source_guid"] for r in _rows(expanding, "split") if r["parent_source_guid"] != selected
    }
    assert len(others) == (RECORDS - 1) * 2
    _fail(expanding, selected, ACTION)

    CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert others <= {r["source_guid"] for r in _rows(expanding, "split")}


def test_a_second_retry_does_not_grow_it_further(expanding):
    selected = _record_ids(expanding, ACTION)[0]
    for _ in range(2):
        _fail(expanding, selected, ACTION)
        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])
        assert result.exit_code == 0, result.output

    assert len(_rows(expanding, "split")) == RECORDS * 2


def test_no_row_is_reported_unresolved(expanding):
    """The diagnostic marks rows the run could not attribute. One mint deep it
    resolves every row, so a warning here would be noise on an ordinary retry."""
    selected = _record_ids(expanding, ACTION)[0]
    _fail(expanding, selected, ACTION)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert "cannot be attributed" not in result.output


COMBINE_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def combine_in_two(data: Any, *args) -> list[dict]:
    summary = str((data or {}).get("summary", ""))
    return [{"summary": f"{summary} /{half}", "exam_density": "low"} for half in (1, 2)]
"""

COMBINE_ACTION = """  - name: combine
    kind: tool
    dependencies: [flatten, split]
    intent: "Combine"
    schema: tool_action_output
    impl: combine_in_two
    context_scope: { observe: [flatten.summary, split.summary] }
    expect: { repair: none }
"""


@pytest.fixture
def diamond(expanding):
    """A third action depending on both `flatten` and the expansion over it.

    Its input therefore holds a record *and* rows descended from that record,
    and a descendant names the record standing beside it as its parent. Nothing
    groups the two back together: the keys `merge_records_by_key` correlates on
    do not include `parent_source_guid`.
    """
    config = expanding / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + COMBINE_ACTION)
    (expanding / "tools" / WORKFLOW / "combine.py").write_text(COMBINE_TOOL)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return expanding


def test_the_diamond_really_puts_a_record_beside_its_own_descendant(diamond):
    """The premise. If the framework merged the two branches back into one
    record this shape would not exist and the guard against it would be dead."""
    parents = {r.get("parent_source_guid") for r in _rows(diamond, "combine")}
    records = set(_record_ids(diamond, ACTION))

    assert parents & records, "no row of `combine` names a `flatten` record as its parent"
    assert len(_rows(diamond, "combine")) > RECORDS * 2, (
        "combine saw only one branch — the diamond did not form"
    )


def test_repairing_a_record_does_not_delete_its_descendants_rows(diamond):
    """A descendant's rows name the repaired record too, so attributing by that
    name alone hands them to the rewrite, which drops them."""
    selected = _record_ids(diamond, ACTION)[0]
    before = {r["source_guid"] for r in _rows(diamond, "combine")}
    _fail(diamond, selected, ACTION)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert result.exit_code == 0, result.output
    after = {r["source_guid"] for r in _rows(diamond, "combine")}
    assert not (before - after), f"rows deleted by the repair: {sorted(before - after)}"

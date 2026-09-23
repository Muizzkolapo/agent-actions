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

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert result.exit_code == 0, result.output
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


class TestARecordTheLimitDropped:
    """A record limit narrows an action's input above the repair.

    The record it drops is still one of that action's inputs. If the gate is not
    told about it, a row of *its* making reads as a row of a repaired record's —
    they name the same parent — and the rewrite deletes it without ever making
    it again. A limit never drops a record the repair named, so telling the gate
    about the dropped ones can only widen what is carried.
    """

    def test_no_row_is_deleted_under_a_limit(self, diamond, monkeypatch):
        selected = _record_ids(diamond, ACTION)[0]
        before = {r["source_guid"] for r in _rows(diamond, "combine")}
        assert before
        _fail(diamond, selected, ACTION)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

        assert result.exit_code == 0, result.output
        after = {r["source_guid"] for r in _rows(diamond, "combine")}
        assert not (before - after), f"rows deleted under a limit: {sorted(before - after)}"

    def test_no_row_is_deleted_under_a_limit_at_the_expansion(self, expanding, monkeypatch):
        """The same at an action with one mint rather than a diamond."""
        selected = _record_ids(expanding, ACTION)[0]
        before = _rows(expanding, "split")
        # Taken before the retry: the repaired record's own rows are replaced, and
        # everything else must still be there afterwards.
        untouched = {r["source_guid"] for r in before if r.get("parent_source_guid") != selected}
        assert len(untouched) == (RECORDS - 1) * 2
        _fail(expanding, selected, ACTION)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

        assert result.exit_code == 0, result.output
        after = {r["source_guid"] for r in _rows(expanding, "split")}
        assert untouched <= after, (
            f"rows of an untouched record deleted: {sorted(untouched - after)}"
        )


# Deliberately not `split.py`: tool discovery imports by module name, so two
# fixtures writing the same basename serve the second one the first one's module.
FILE_SPLIT_TOOL = '''from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool(granularity=Granularity.FILE)
def fsplit_all(data: Any, *args) -> Any:
    """Two rows per record, handed the whole file at once."""
    return FileUDFResult(
        [
            {
                "source_index": index,
                "data": {
                    "summary": f"{record.get('summary')} |{half}",
                    "exam_density": "high",
                },
            }
            for index, record in enumerate(data or [])
            for half in (1, 2)
        ]
    )
'''

FILE_SPLIT_ACTION = """  - name: fsplit
    kind: tool
    granularity: File
    dependencies: [flatten]
    intent: "Split at file granularity"
    schema: tool_action_output
    impl: fsplit_all
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


@pytest.fixture
def file_granularity(project):  # noqa: F811
    """An expanding action at FILE granularity.

    The pipeline forks on `granularity` and hands the two branches different
    arguments; an action with no `granularity:` key takes the RECORD branch. So
    a suite built only from those leaves the FILE branch's wiring unpinned, and
    it is the branch the reported bug names.
    """
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + FILE_SPLIT_ACTION)
    (project / "tools" / WORKFLOW / "fsplit.py").write_text(FILE_SPLIT_TOOL)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return project


class TestAtFileGranularity:
    def test_the_action_really_mints_at_this_granularity(self, file_granularity):
        rows = _rows(file_granularity, "fsplit")
        assert len(rows) == RECORDS * 2
        assert {r["source_guid"] for r in rows}.isdisjoint(
            set(_record_ids(file_granularity, ACTION))
        )

    def test_a_retry_deletes_no_row_and_does_not_grow_the_output(self, file_granularity):
        selected = _record_ids(file_granularity, ACTION)[0]
        before = _rows(file_granularity, "fsplit")
        untouched = {r["source_guid"] for r in before if r.get("parent_source_guid") != selected}
        assert len(untouched) == (RECORDS - 1) * 2
        _fail(file_granularity, selected, ACTION)

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

        assert result.exit_code == 0, result.output
        after = {r["source_guid"] for r in _rows(file_granularity, "fsplit")}
        assert untouched <= after, f"rows deleted at FILE granularity: {sorted(untouched - after)}"
        assert len(_rows(file_granularity, "fsplit")) == RECORDS * 2
        # The FILE branch hands the gate its own list, and giving it the narrowed
        # one resolves nothing: every untouched row reads as unattributable. The
        # rows survive either way here, so the diagnostic is what tells the two
        # apart — and on a shape that can hold a diamond it is a deletion.
        assert "cannot be attributed" not in result.output

    def test_the_named_rows_are_replaced_while_a_limit_drops_other_records(
        self, file_granularity, monkeypatch
    ):
        """The positive half, at FILE granularity and under a limit.

        Everything else here asserts that nothing vanished, which a repair doing
        nothing at all satisfies. This one asserts the work happened: the named
        record's rows are gone and replaced by new ones. Under a limit at the
        same time, because the two arms of the granularity fork capture the
        input separately and only one of them was ever pinned above the limit.
        """
        selected = _record_ids(file_granularity, ACTION)[0]
        before = _rows(file_granularity, "fsplit")
        stale = {r["source_guid"] for r in before if r.get("parent_source_guid") == selected}
        untouched = {r["source_guid"] for r in before if r.get("parent_source_guid") != selected}
        assert len(stale) == 2
        assert len(untouched) == (RECORDS - 1) * 2
        _fail(file_granularity, selected, ACTION)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

        assert result.exit_code == 0, result.output
        after = _rows(file_granularity, "fsplit")
        guids = {r["source_guid"] for r in after}
        fresh = {r["source_guid"] for r in after if r.get("parent_source_guid") == selected}
        assert stale.isdisjoint(guids), "the named record's rows were not replaced"
        assert len(fresh) == 2, "the named record was not re-run"
        assert untouched <= guids, (
            f"rows of a record the limit dropped were deleted: {sorted(untouched - guids)}"
        )
        assert "cannot be attributed" not in result.output

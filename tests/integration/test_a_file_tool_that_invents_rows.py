"""A FILE tool's synthetic row — one it invented rather than derived from an input.

``source_index: None`` declares that no single input produced a row, and the
framework mints it an identity that joins nothing upstream. Driven through the
`agac run` CLI, because the marking only matters once the row has been through
storage and the action below has read it back.
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

ROLL_UP_TOOL = '''from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool(granularity=Granularity.FILE)
def roll_up_all(data: Any, *args) -> Any:
    """Two rows no single input produced: the declared synthetic shape."""
    return FileUDFResult(
        [
            {
                "source_index": None,
                "data": {
                    "summary": f"rollup {half} over {len(data or [])}",
                    "exam_density": "high",
                },
            }
            for half in (1, 2)
        ]
    )
'''

LABEL_TOOL = '''from typing import Any

from agent_actions import udf_tool


@udf_tool
def label_rollup(data: Any, *args) -> list[dict]:
    """Echo a field from above the roll-up. A declared namespace is handed over
    even when the record has none, with null fields, so an absent value has to
    read as empty rather than as the string "None"."""
    above = (data or {}).get("flatten") or {}
    return [{"summary": str(above.get("exam_density") or ""), "exam_density": "seen"}]
'''

INVENTING_ACTIONS = """  - name: roll_up
    kind: tool
    granularity: File
    dependencies: [flatten]
    intent: "Roll the file up into two invented rows"
    schema: tool_action_output
    impl: roll_up_all
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
  - name: label
    kind: tool
    dependencies: [roll_up]
    intent: "Echo what the roll-up still carries from flatten"
    schema: tool_action_output
    impl: label_rollup
    context_scope: { observe: [roll_up.summary, flatten.exam_density] }
    expect: { repair: none }
"""


@pytest.fixture
def inventing(project):  # noqa: F811
    """Six records flattened, rolled up into two invented rows, then read back.

    `label` observes a namespace from *above* the roll-up, so it can only answer
    if the invented rows still carry what came before them.
    """
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + INVENTING_ACTIONS)
    (project / "tools" / WORKFLOW / "roll_up.py").write_text(ROLL_UP_TOOL)
    (project / "tools" / WORKFLOW / "label.py").write_text(LABEL_TOOL)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return project


def _raw(project, action):  # noqa: F811
    backend = _backend(project)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend._read_target_raw(action, path)
        ]
    finally:
        backend.close()


def _read_back(project, action):  # noqa: F811
    backend = _backend(project)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def test_the_fixture_really_invents(inventing):
    """The premise, asserted: two rows, and neither is any input's row. Without
    this the rest could pass against an ordinary one-to-one action."""
    rows = _raw(inventing, "roll_up")

    assert len(rows) == 2
    assert {r["source_guid"] for r in rows}.isdisjoint(set(_record_ids(inventing, ACTION)))


def test_an_invented_row_still_carries_what_came_before_it(inventing):
    """Read back, not as written: the loss is in the rejoin, so a raw row looks
    the same either way."""
    read_back = _read_back(inventing, "roll_up")

    assert [sorted(r.get("content", {})) for r in read_back] == [
        ["flatten", "roll_up", "source"],
        ["flatten", "roll_up", "source"],
    ]


def test_the_action_below_reads_a_value_from_above_the_roll_up(inventing):
    """The user-visible end of it: `label` observes `flatten.exam_density` and
    echoes what it was handed. The namespace is declared, so it is handed over
    either way — what distinguishes the two is whether the value came with it."""
    echoed = {r["content"]["label"]["summary"] for r in _raw(inventing, "label")}
    above = {r["content"]["flatten"]["exam_density"] for r in _raw(inventing, ACTION)}

    assert echoed == above == {"low"}


def test_the_expectation_below_passes_on_what_it_is_handed(inventing):
    """`summary_present` fails on an empty string, so a namespace the roll-up
    dropped reaches the user as a failed expectation, not only as thin content."""
    verdicts = [r["content"]["label"]["expect"]["overall_pass"] for r in _raw(inventing, "label")]

    assert verdicts == [True, True]


def test_an_invented_row_is_given_no_producer_of_its_own(inventing):
    """Nothing is added here: no single input produced the row.

    It ends up with none at all only because this workflow's inputs carry none to
    inherit — the envelope hands on whatever the stand-in record had, and clearing
    that is what #1046 blocks. So this pins "adds none", not "has none"; the
    unit suite covers the inherited case.
    """
    parents = {r.get("parent_source_guid") for r in _raw(inventing, "roll_up")}

    assert parents == {None}


def test_a_retry_below_it_still_says_it_cannot_attribute_these_rows(inventing):
    """The diagnostic that survives because the row claims nothing. The rerun
    regenerates rows the gate also hands back, and this warning is the only
    thing that tells a user so — see #1022 for the duplication itself."""
    selected = _record_ids(inventing, ACTION)[1]
    _fail(inventing, selected, ACTION)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert result.exit_code == 0, result.output
    assert "cannot be attributed" in result.output


def test_the_records_it_rolled_up_are_all_still_accounted_for(inventing):
    """A guard, not a symptom: a synthetic output accounts for every input by
    being synthetic, and the rows above it must not start being tombstoned as
    records the tool forgot."""
    assert len(_raw(inventing, ACTION)) == RECORDS


def test_what_a_retry_does_to_a_row_no_single_record_produced(inventing):
    """Pinned as numbers so the growth cannot worsen unnoticed.

    Every retry carries the stored rows back beside the ones the rerun makes
    again, because an aggregating action recomputes over whatever input the
    repair narrowed it to and the gate cannot match the results up. This branch
    does not change that — it keeps the rows attributable-to-nothing, so the
    warning above still fires. Closing it needs the field in #1022.
    """
    ids = _record_ids(inventing, ACTION)
    counts = [len(_raw(inventing, "roll_up"))]

    for selected in (ids[0], ids[1]):
        _fail(inventing, selected, ACTION)
        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])
        assert result.exit_code == 0, result.output
        counts.append(len(_raw(inventing, "roll_up")))

    assert counts == [2, 4, 6], f"the retry behaviour changed: {counts}"


def test_a_row_carried_past_a_retry_keeps_what_came_before_it(inventing):
    """Counting the rows is not enough — they can survive and be gutted.

    A carried row is read back reconstructed, and the mode it was stored under
    does not survive that read, so it would be re-stored as a delta against an
    identity nothing upstream holds and come back with only this action's
    namespace. That is the loss this ticket exists to stop, returning on the
    first repair.
    """
    selected = _record_ids(inventing, ACTION)[1]
    _fail(inventing, selected, ACTION)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])
    assert result.exit_code == 0, result.output

    namespaces = [sorted(r.get("content", {})) for r in _read_back(inventing, "roll_up")]
    assert namespaces == [["flatten", "roll_up", "source"]] * len(namespaces)
    assert len(namespaces) == 4

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


def test_an_invented_row_says_which_identity_to_resolve_it_by(inventing):
    """Its own guid matches nothing in the source pool, so it must name one that
    does or `resolve_source_content` dead-ends on it."""
    staged = set(_record_ids(inventing, ACTION))
    parents = {r.get("parent_source_guid") for r in _raw(inventing, "roll_up")}

    assert parents <= staged
    assert None not in parents


def test_the_records_it_rolled_up_are_all_still_accounted_for(inventing):
    """A guard, not a symptom: a synthetic output accounts for every input by
    being synthetic, and the rows above it must not start being tombstoned as
    records the tool forgot."""
    assert len(_raw(inventing, ACTION)) == RECORDS

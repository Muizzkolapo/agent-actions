"""merge_fan_in pairs a branch's split records with the record they came from."""

import pytest

from agent_actions.errors import WorkflowError
from agent_actions.workflow.merge import merge_fan_in


def _record(branch: str, guid: str, value: str, parent: str | None = None) -> dict:
    record = {"source_guid": guid, "content": {"source": {"id": "s"}, branch: {"v": value}}}
    if parent:
        record["parent_source_guid"] = parent
    return record


def _values(merged: list[dict]) -> list[tuple]:
    return sorted(
        (r["content"].get("left", {}).get("v", "-"), r["content"].get("right", {}).get("v", "-"))
        for r in merged
    )


def test_each_split_record_is_merged_with_the_record_of_its_source():
    merged = merge_fan_in(
        [
            ("left", [_record("left", "P", "L")]),
            ("right", [_record("right", "r1", "R1", "P"), _record("right", "r2", "R2", "P")]),
        ]
    )

    assert _values(merged) == [("L", "R1"), ("L", "R2")]
    assert sorted(r["source_guid"] for r in merged) == ["r1", "r2"]


def test_records_of_one_source_in_every_branch_merge_as_before():
    merged = merge_fan_in(
        [("left", [_record("left", "P", "L")]), ("right", [_record("right", "P", "R")])]
    )

    assert _values(merged) == [("L", "R")]


def test_two_branches_that_each_split_one_source_raise():
    with pytest.raises(WorkflowError, match="left.*right"):
        merge_fan_in(
            [
                ("left", [_record("left", f"l{n}", f"L{n}", "P") for n in (1, 2)]),
                ("right", [_record("right", f"r{n}", f"R{n}", "P") for n in (1, 2)]),
            ]
        )


def test_branches_below_an_earlier_split_missing_different_records_do_not_raise():
    """Both branches read split records s1, s2 of P; each lacks a different one."""
    merged = merge_fan_in(
        [
            ("left", [_record("left", "s1", "L1", "P")]),
            ("right", [_record("right", "s2", "R2", "P")]),
        ]
    )

    assert _values(merged) == [("-", "R2"), ("L1", "-")]

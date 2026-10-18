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


def test_branches_that_share_no_record_of_a_split_source_raise():
    """One record of P each and neither is the other's: whether each branch split P on its
    own or each lacks a different record of one split, nothing here pairs."""
    with pytest.raises(WorkflowError, match="left.*right"):
        merge_fan_in(
            [
                ("left", [_record("left", "s1", "L1", "P")]),
                ("right", [_record("right", "s2", "R2", "P")]),
            ]
        )


def test_a_branch_that_split_a_source_beside_others_paired_under_it_raises():
    with pytest.raises(WorkflowError, match="right"):
        merge_fan_in(
            [
                ("left", [_record("left", f"s{n}", f"L{n}", "P") for n in (1, 2)]),
                ("mid", [_record("mid", f"s{n}", f"M{n}", "P") for n in (1, 2)]),
                ("right", [_record("right", f"r{n}", f"R{n}", "P") for n in (1, 2)]),
            ]
        )


def test_branches_below_an_earlier_split_missing_different_records_do_not_raise():
    """Both branches read split records s1..s3 of P and pair on s3; each lacks a
    different one of the others, which run as they are."""
    merged = merge_fan_in(
        [
            ("left", [_record("left", "s1", "L1", "P"), _record("left", "s3", "L3", "P")]),
            ("right", [_record("right", "s2", "R2", "P"), _record("right", "s3", "R3", "P")]),
        ]
    )

    assert _values(merged) == [("-", "R2"), ("L1", "-"), ("L3", "R3")]


def test_a_split_paired_below_an_earlier_split_vouches_for_its_branch():
    """`right` splits each record of an earlier split of P and lacks one; its split
    records of s1 pair with `left`'s s1, so those of s2 are a lack, not a second split."""
    merged = merge_fan_in(
        [
            ("left", [_record("left", "s1", "L1", "P")]),
            (
                "right",
                [
                    {**_record("right", f"r{n}", f"R{n}", "P"), "producer_source_guids": [s]}
                    for n, s in ((1, "s1"), (2, "s1"), (3, "s2"))
                ],
            ),
        ]
    )

    assert _values(merged) == [("-", "R3"), ("L1", "R1"), ("L1", "R2")]


def _split(branch: str, guid: str, value: str, producer: str) -> dict:
    return {**_record(branch, guid, value, "P"), "producer_source_guids": [producer]}


SPLIT_AND_ITS_SPLIT = {
    "left": [_record("left", "P", "L")],
    "right": [_split("right", f"s{n}", f"R{n}", "P") for n in (1, 2)],
    "again": [_split("again", f"s{n}{e}", f"A{n}{e}", f"s{n}") for n in (1, 2) for e in "xy"],
}


def _triples(merged: list[dict]) -> list[tuple]:
    return sorted(
        tuple(r["content"].get(b, {}).get("v", "-") for b in ("left", "right", "again"))
        for r in merged
    )


@pytest.mark.parametrize("order", [("left", "right", "again"), ("again", "right", "left")])
def test_a_split_of_a_split_pairs_with_its_split_and_their_source(order):
    merged = merge_fan_in([(branch, SPLIT_AND_ITS_SPLIT[branch]) for branch in order])

    assert _triples(merged) == sorted(("L", f"R{n}", f"A{n}{e}") for n in (1, 2) for e in "xy")
    assert sorted(r["source_guid"] for r in merged) == ["s1x", "s1y", "s2x", "s2y"]


def test_a_split_none_of_whose_own_split_is_pooled_still_pairs_with_its_source():
    merged = merge_fan_in(
        [
            ("again", SPLIT_AND_ITS_SPLIT["again"][:2]),
            ("right", SPLIT_AND_ITS_SPLIT["right"]),
            ("left", SPLIT_AND_ITS_SPLIT["left"]),
        ]
    )

    assert _triples(merged) == [("L", "R1", "A1x"), ("L", "R1", "A1y"), ("L", "R2", "-")]


def test_a_split_of_a_split_beside_a_second_split_of_the_source_raises():
    with pytest.raises(WorkflowError, match="other.*right"):
        merge_fan_in(
            [
                *SPLIT_AND_ITS_SPLIT.items(),
                ("other", [_split("other", f"o{n}", f"O{n}", "P") for n in (1, 2)]),
            ]
        )


def test_a_branch_holding_a_source_and_a_split_of_its_split_raises():
    """`left` holds P and a record split from `right`'s split of P: merged along the
    chain, one record would carry two of `left`'s."""
    with pytest.raises(WorkflowError, match="left"):
        merge_fan_in(
            [
                ("left", [_record("left", "P", "L"), _split("left", "s1x", "L1x", "s1")]),
                ("right", [_split("right", "s1", "R1", "P")]),
            ]
        )


def _aggregate(branch: str, value: str, made_by: str = "right") -> dict:
    """A row a FILE tool returned with `source_index: None`: it belongs to no source."""
    return {**_record(branch, "agg", value), "aggregated_by": made_by}


def test_an_aggregate_one_branch_holds_raises_naming_the_branch_and_its_maker():
    with pytest.raises(WorkflowError, match=r"right.*source_index"):
        merge_fan_in(
            [
                ("left", [_record("left", "P", "L")]),
                ("right", [_record("right", "P", "R"), _aggregate("right", "total")]),
            ]
        )


def test_an_aggregate_carried_below_its_maker_raises_naming_the_maker():
    with pytest.raises(WorkflowError, match="tally"):
        merge_fan_in(
            [
                ("left", [_record("left", "P", "L")]),
                ("loud", [_record("loud", "P", "R"), _aggregate("loud", "TOTAL", "tally")]),
            ]
        )


def test_an_aggregate_every_branch_reads_pairs_like_any_record():
    merged = merge_fan_in(
        [("left", [_aggregate("left", "L")]), ("right", [_aggregate("right", "R")])]
    )

    assert _values(merged) == [("L", "R")]


def test_an_aggregate_over_split_records_does_not_pair_with_their_source():
    """Built over its file's first record, the aggregate carries that record's
    `parent_source_guid`; it is still no record of that source."""
    over_a_split = {**_aggregate("right", "total"), "parent_source_guid": "P"}
    with pytest.raises(WorkflowError, match="source_index"):
        merge_fan_in([("left", [_record("left", "P", "L")]), ("right", [over_a_split])])


def test_a_split_of_an_aggregate_pairs_with_the_aggregate():
    split = [
        {**_record("again", f"t{n}", f"A{n}", "agg"), "aggregated_by": "right"} for n in (1, 2)
    ]
    merged = merge_fan_in([("right", [_aggregate("right", "R")]), ("again", split)])

    assert sorted((r["content"]["right"]["v"], r["content"]["again"]["v"]) for r in merged) == [
        ("R", "A1"),
        ("R", "A2"),
    ]


def _folded_into(branch: str, guid: str, value: str, folded: dict[str, str]) -> dict:
    """A row a FILE tool returned naming several inputs: it carries the first one's id."""
    return {**_record(branch, guid, value), "folded_sources": folded}


def test_a_record_folded_into_another_row_is_merged_blocked_naming_that_row():
    merged = merge_fan_in(
        [
            ("left", [_record("left", "A", "LA"), _record("left", "B", "LB")]),
            ("right", [_folded_into("right", "A", "RAB", {"B": "fold"})]),
        ]
    )

    by_guid = {r["source_guid"]: r for r in merged}
    assert by_guid["A"]["content"]["right"]["v"] == "RAB"
    assert "_state" not in by_guid["A"]
    blocked = by_guid["B"]
    assert blocked["_state"] == "cascade_skipped"
    assert blocked["metadata"]["fan_in_consumed_into"] == "A"
    assert blocked["metadata"]["upstream_action"] == "fold"
    assert blocked["metadata"]["upstream_reason"] == "consumed_into_output"
    assert blocked["content"]["right"] is None
    assert blocked["content"]["left"] == {"v": "LB"}


def test_a_record_a_branch_lacks_without_folding_it_runs_as_before():
    merged = merge_fan_in(
        [
            ("left", [_record("left", "A", "LA"), _record("left", "B", "LB")]),
            ("right", [_folded_into("right", "A", "RA", {"C": "fold"})]),
        ]
    )

    assert all("_state" not in r for r in merged)


def test_a_folded_record_every_branch_still_holds_pairs_as_before():
    merged = merge_fan_in(
        [
            ("left", [_record("left", "A", "LA"), _record("left", "B", "LB")]),
            (
                "right",
                [_folded_into("right", "A", "RAB", {"B": "fold"}), _record("right", "B", "RB")],
            ),
        ]
    )

    assert _values(merged) == [("LA", "RAB"), ("LB", "RB")]
    assert all("_state" not in r for r in merged)


def test_a_folded_record_already_blocked_keeps_its_own_cause():
    failed = {**_record("left", "B", "LB"), "_state": "failed"}
    merged = merge_fan_in(
        [
            ("left", [_record("left", "A", "LA"), failed]),
            ("right", [_folded_into("right", "A", "RAB", {"B": "fold"})]),
        ]
    )

    blocked = next(r for r in merged if r["source_guid"] == "B")
    assert blocked["_state"] == "failed"
    assert "fan_in_consumed_into" not in (blocked.get("metadata") or {})

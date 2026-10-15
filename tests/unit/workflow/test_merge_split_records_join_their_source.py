"""A record split from a pooled record joins that record's group at a fan-in."""

from agent_actions.workflow.merge import merge_records_by_key


def _left(guid, **extra):
    return {"source_guid": guid, "content": {"left": {"v": f"L-{guid}"}}, **extra}


def _split(guid, producer, ancestor, **extra):
    return {
        "source_guid": guid,
        "parent_source_guid": ancestor,
        "producer_source_guids": [producer],
        "content": {"right": {"v": guid}},
        **extra,
    }


def _pairs(result):
    return sorted(
        (r["source_guid"], r["content"].get("left", {}).get("v"), r["content"]["right"]["v"])
        for r in result
        if "right" in r["content"]
    )


def test_each_split_record_merges_with_its_source_and_keeps_its_own_identity():
    records = [_left("a"), _split("a1", "a", "a"), _split("a2", "a", "a")]

    result = merge_records_by_key(records)

    assert len(result) == 2
    assert _pairs(result) == [("a1", "L-a", "a1"), ("a2", "L-a", "a2")]


def test_the_input_it_consumed_decides_not_the_earliest_ancestor():
    """Below an expansion both branches name the same ancestor, `s`, which no branch holds."""
    records = [
        _left("x", parent_source_guid="s"),
        _left("y", parent_source_guid="s"),
        _split("x1", "x", "s"),
        _split("y1", "y", "s"),
    ]

    result = merge_records_by_key(records)

    assert _pairs(result) == [("x1", "L-x", "x1"), ("y1", "L-y", "y1")]


def test_a_pool_keyed_on_version_correlation_still_joins_the_split():
    records = [
        _left("a", version_correlation_id="corr_a"),
        _split("a1", "a", "a", version_correlation_id="corr_a1"),
        _split("a2", "a", "a", version_correlation_id="corr_a2"),
    ]

    result = merge_records_by_key(records)

    assert _pairs(result) == [("a1", "L-a", "a1"), ("a2", "L-a", "a2")]


def test_a_split_whose_input_is_not_pooled_passes_through_alone():
    records = [_left("b"), _split("a1", "a", "a")]

    result = merge_records_by_key(records)

    assert sorted(r["source_guid"] for r in result) == ["a1", "b"]
    assert _pairs(result) == [("a1", None, "a1")]


def test_a_row_that_kept_its_identity_and_consumed_another_input_joins_nothing():
    """A many-to-one row keeps `x` and names `y` as consumed; `y` still merges on its own."""
    records = [
        {"source_guid": "x", "producer_source_guids": ["y"], "content": {"agg": {"v": "x+y"}}},
        {"source_guid": "x", "content": {"other": {"v": "x"}}},
        {"source_guid": "y", "content": {"other": {"v": "y"}}},
    ]

    result = merge_records_by_key(records)

    by_guid = {r["source_guid"]: r["content"] for r in result}
    assert by_guid == {
        "x": {"agg": {"v": "x+y"}, "other": {"v": "x"}},
        "y": {"other": {"v": "y"}},
    }


def test_a_row_naming_its_own_group_as_producer_is_neither_lost_nor_doubled():
    records = [
        _left("a", version_correlation_id="corr_a"),
        _split("a1", "a", "a", version_correlation_id="corr_a"),
    ]

    result = merge_records_by_key(records)

    assert len(result) == 1
    assert set(result[0]["content"]) == {"left", "right"}


def test_a_row_made_from_several_pooled_records_joins_none_of_them():
    records = [
        _left("a"),
        _left("b"),
        {
            "source_guid": "ab",
            "producer_source_guids": ["a", "b"],
            "content": {"right": {"v": "ab"}},
        },
    ]

    result = merge_records_by_key(records)

    assert sorted(r["source_guid"] for r in result) == ["a", "ab", "b"]


def test_a_group_whose_records_name_different_sources_joins_neither():
    records = [
        _left("y", version_correlation_id="corr_y"),
        _left("z", version_correlation_id="corr_z"),
        _split("x", "y", "y", version_correlation_id="corr_x"),
        _split("x2", "z", "z", version_correlation_id="corr_x"),
    ]

    result = merge_records_by_key(records)

    assert sorted(r["source_guid"] for r in result) == ["x", "y", "z"]


def test_records_naming_only_each_other_in_one_group_are_neither_lost_nor_doubled():
    records = [
        _split("p", "q", "s", version_correlation_id="corr_pq"),
        {**_left("q", version_correlation_id="corr_pq"), "producer_source_guids": ["p"]},
    ]

    result = merge_records_by_key(records)

    assert len(result) == 1
    assert set(result[0]["content"]) == {"left", "right"}


def test_a_row_that_kept_its_identity_joins_nothing_when_its_other_branch_is_absent():
    """`A` kept its identity and consumed `B`; the other branch holds no `A`, only `B`."""
    records = [
        {"source_guid": "A", "producer_source_guids": ["B"], "content": {"left": {"v": "A+B"}}},
        {"source_guid": "B", "content": {"right": {"v": "B"}}},
    ]

    result = merge_records_by_key(records)

    assert sorted((r["source_guid"], sorted(r["content"])) for r in result) == [
        ("A", ["left"]),
        ("B", ["right"]),
    ]

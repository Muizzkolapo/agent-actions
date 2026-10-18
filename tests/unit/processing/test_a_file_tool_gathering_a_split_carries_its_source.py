"""A FILE tool row gathered from every record split from one source is that source's row.

Kept at the first split record's identity it pairs with nothing in a fan-in beside a
branch that split the same source (#1509).
"""

from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.pipeline_file_mode import reconcile_outputs


def split(guid, source):
    return {
        "source_guid": guid,
        "parent_source_guid": source,
        "content": {"right": {"tag": guid}},
    }


def gathered(*index_lists):
    return FileUDFResult(
        [{"source_index": list(indices), "data": {"tag": "+"}} for indices in index_lists]
    )


SPLITS = [split("A1", "A"), split("A2", "A"), split("B1", "B"), split("B2", "B")]


def test_a_row_gathered_from_each_split_record_of_a_source_takes_its_identity():
    rows, _ = reconcile_outputs(gathered([0, 1], [2, 3]), "gather", SPLITS)

    assert [row["source_guid"] for row in rows] == ["A", "B"]
    assert [row.get("parent_source_guid") for row in rows] == [None, None]


def test_it_names_every_split_record_it_consumed_as_a_producer():
    """Its identity is no input's, so carry-forward and repair place it through these."""
    rows, _ = reconcile_outputs(gathered([0, 1], [2, 3]), "gather", SPLITS)

    assert [row["producer_source_guids"] for row in rows] == [["A1", "A2"], ["B1", "B2"]]
    assert all(row["_delta_mode"] == "full" for row in rows)


def test_a_row_gathered_from_several_sources_keeps_its_first_input():
    rows, _ = reconcile_outputs(gathered([0, 1, 2, 3]), "gather", SPLITS)

    assert rows[0]["source_guid"] == "A1"


def test_a_row_gathered_from_part_of_a_split_keeps_its_first_input():
    """Another row holds a record of the same split, so this one is not the source's."""
    records = [*SPLITS[:2], split("A3", "A")]
    rows, _ = reconcile_outputs(gathered([0, 1], [2]), "gather", records)

    assert [row["source_guid"] for row in rows] == ["A1", "A3"]


def test_a_split_record_the_file_holds_but_no_row_names_leaves_the_identity_alone():
    records = [*SPLITS[:2], split("A3", "A")]
    rows, _ = reconcile_outputs(gathered([0, 1]), "gather", records)

    assert rows[0]["source_guid"] == "A1"


def test_a_single_split_record_keeps_its_identity():
    rows, _ = reconcile_outputs(gathered([0], [1]), "gather", SPLITS[:2])

    assert [row["source_guid"] for row in rows] == ["A1", "A2"]


def test_a_gather_beside_the_source_record_itself_keeps_its_first_input():
    """The source's own record is in the file: a second row under its identity."""
    records = [{"source_guid": "A", "content": {"right": {"tag": "A"}}}, *SPLITS[:2]]
    rows, _ = reconcile_outputs(gathered([0], [1, 2]), "gather", records)

    assert [row["source_guid"] for row in rows] == ["A", "A1"]


def test_unsplit_records_gathered_together_keep_the_first_identity():
    records = [{"source_guid": g, "content": {"right": {"tag": g}}} for g in ("A", "B")]
    rows, _ = reconcile_outputs(gathered([0, 1]), "gather", records)

    assert rows[0]["source_guid"] == "A"


def test_a_gather_whose_records_another_row_also_names_keeps_its_first_input():
    """Two rows would answer for one split record; the gather is not the source alone."""
    raw = FileUDFResult(
        [
            {"source_index": [0, 1], "data": {"tag": "+"}},
            {"source_index": 1, "data": {"tag": "again"}},
        ]
    )
    rows, _ = reconcile_outputs(raw, "gather", SPLITS[:2])

    assert rows[0]["source_guid"] != "A"


def test_the_only_split_record_left_in_the_file_keeps_its_identity():
    rows, _ = reconcile_outputs(gathered([0]), "gather", SPLITS[:1])

    assert rows[0]["source_guid"] == "A1"

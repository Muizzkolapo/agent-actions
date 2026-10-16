"""A collected batch file holds the rows that answer for the inputs recorded for it."""

from agent_actions.llm.batch.services.collect import _rows_answering_inputs


def _row(guid, *, producers=None):
    row = {"source_guid": guid}
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


def _guids(rows):
    return [row["source_guid"] for row in rows]


def test_a_row_for_a_record_that_left_is_dropped():
    rows = [_row("a1"), _row("a2")]

    assert _guids(_rows_answering_inputs(rows, ["a1"])) == ["a1"]


def test_a_minted_row_is_kept_while_its_input_is_one_and_dropped_when_it_is_not():
    rows = [
        _row("m1", producers=["a1"]),
        _row("m2", producers=["a1"]),
        _row("m3", producers=["a2"]),
    ]

    assert _guids(_rows_answering_inputs(rows, ["a1"])) == ["m1", "m2"]


def test_a_row_naming_several_inputs_is_kept_while_any_is_one():
    rows = [_row("x", producers=["a1", "a2"])]

    assert _guids(_rows_answering_inputs(rows, ["a2"])) == ["x"]


def test_a_row_with_no_identity_is_kept():
    rows = [{"content": {}}, _row("a2")]

    assert _rows_answering_inputs(rows, ["a1"]) == [{"content": {}}]


def test_with_no_inputs_recorded_every_row_is_kept():
    rows = [_row("a1"), _row("a2")]

    assert _rows_answering_inputs(rows, []) == rows

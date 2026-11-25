"""`--rerun ACTION --where/--records` chooses records from the rows ACTION stored.

A row the action made from other records is named by those records too: named by
its own id alone, the action ran on nothing while what reads it answered again.
"""

import click
import pytest

from agent_actions.cli.rerun_selection import (
    RecordFilter,
    read_record_ids,
    refuse_an_expression_that_does_not_parse,
    select_records,
)


def _row(guid: str, label: str, **identity) -> dict:
    return {"source_guid": guid, "content": {"classify": {"label": label}}, **identity}


ROWS = [_row("a", "other"), _row("b", "billing"), _row("c", "other")]


def _all_held(ids):
    return set(ids)


def _select(record_filter: RecordFilter, rows=ROWS, held=_all_held):
    return select_records(rows, "classify", record_filter, held)


def test_an_expression_matches_the_records_whose_stored_fields_satisfy_it():
    selection = _select(RecordFilter(where='classify.label == "other"'))

    assert selection.matched == ["a", "c"]
    assert selection.named == {"a", "c"}
    assert (selection.considered, selection.kept) == (3, 1)


def test_listed_ids_match_those_records():
    selection = _select(RecordFilter(record_ids=("b",)))

    assert selection.matched == ["b"]


def test_with_both_a_record_must_be_listed_and_match():
    selection = _select(RecordFilter(where='classify.label == "other"', record_ids=("a", "b")))

    assert selection.matched == ["a"]


def test_an_id_that_names_no_record_is_refused_by_name():
    with pytest.raises(click.ClickException) as refused:
        _select(RecordFilter(record_ids=("a", "nope"), records_from="ids.txt"))

    assert "1 of the 2 id(s) in ids.txt name no record" in refused.value.message
    assert "nope" in refused.value.message


def test_no_match_selects_nothing():
    selection = _select(RecordFilter(where='classify.label == "refund"'))

    assert (selection.matched, selection.named) == ([], set())


def test_a_field_no_record_holds_is_refused_as_a_mistake():
    with pytest.raises(click.ClickException, match="could not be evaluated on any record"):
        _select(RecordFilter(where='classify.lable == "other"'))


def test_a_record_without_the_field_is_not_matched_and_is_counted():
    rows = [*ROWS, {"source_guid": "d", "content": {"source": {}}}]

    selection = _select(RecordFilter(where='classify.label == "other"'), rows=rows)

    assert selection.matched == ["a", "c"]
    assert selection.unevaluated == 1


def test_a_row_the_action_made_from_another_record_names_that_record_and_itself():
    rows = [
        _row("slot-1", "other", parent_source_guid="ticket-1", producer_source_guids=["ticket-1"]),
        _row("slot-2", "billing", parent_source_guid="ticket-1"),
        _row("slot-3", "other", parent_source_guid="ticket-2"),
    ]

    def tickets_only(ids):
        return {i for i in ids if i.startswith("ticket")}

    selection = _select(RecordFilter(where='classify.label == "other"'), rows, tickets_only)

    assert selection.matched == ["slot-1", "slot-3"]
    assert selection.named == {"ticket-1", "slot-1", "ticket-2", "slot-3"}


def test_a_listed_id_may_be_the_record_a_row_was_made_from():
    rows = [_row("slot-1", "other", parent_source_guid="ticket-1")]

    selection = _select(RecordFilter(record_ids=("ticket-1",)), rows, lambda ids: {"ticket-1"})

    assert selection.matched == ["slot-1"]


def test_a_row_carried_through_keeps_its_own_id_whatever_its_parent():
    # Below an expansion every row names the ancestor as its parent, and is itself the input.
    rows = [_row("slot-1", "other", parent_source_guid="ticket-1")]

    selection = _select(RecordFilter(where='classify.label == "other"'), rows, _all_held)

    assert selection.named == {"slot-1"}


def test_a_matched_row_that_traces_to_no_input_record_is_refused():
    rows = [_row("orphan", "other", parent_source_guid="gone")]

    with pytest.raises(click.ClickException, match="cannot be traced to a record it reads"):
        _select(RecordFilter(where='classify.label == "other"'), rows, lambda ids: set())


def test_an_id_file_skips_blank_lines_comments_and_repeats(tmp_path):
    listed = tmp_path / "ids.txt"
    listed.write_text("# chosen by hand\na\n\n  b  \na\n")

    assert read_record_ids(str(listed)) == ("a", "b")


@pytest.mark.parametrize("text", ["", "# nothing\n"])
def test_an_id_file_that_names_no_record_is_refused(tmp_path, text):
    listed = tmp_path / "ids.txt"
    listed.write_text(text)

    with pytest.raises(click.UsageError, match="names no record"):
        read_record_ids(str(listed))


def test_an_expression_that_does_not_parse_is_refused():
    with pytest.raises(click.UsageError, match="--where is not a guard expression"):
        refuse_an_expression_that_does_not_parse("classify.label ==")

    refuse_an_expression_that_does_not_parse('classify.label IN ["a", "b"] AND source.id > 3')


def test_a_versioned_action_stores_a_row_a_version_and_a_record_is_chosen_once():
    rows = [
        {"source_guid": "a", "content": {"score_1": {"urgency": 5}}},
        {"source_guid": "b", "content": {"score_1": {"urgency": 1}}},
        {"source_guid": "a", "content": {"score_2": {"urgency": 5}}},
        {"source_guid": "b", "content": {"score_2": {"urgency": 2}}},
    ]

    selection = select_records(rows, "score", RecordFilter(record_ids=("a",)), _all_held)

    assert (selection.considered, selection.matched, selection.kept) == (2, ["a"], 1)

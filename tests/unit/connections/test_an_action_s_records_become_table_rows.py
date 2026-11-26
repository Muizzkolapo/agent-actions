"""An output is one row a record: its identity, carried source fields, the action's fields."""

import pytest

from agent_actions.config.schema import OutputConfig
from agent_actions.connections import ColumnType, WriteMode
from agent_actions.connections.export import (
    column_types,
    output_table,
    write_output,
    write_outputs,
)
from agent_actions.connections.sqlite import SqliteConnector
from agent_actions.errors import ConfigurationError


def _record(guid: str, answer, source=None, state: str = "active") -> dict:
    content = {"source": source or {}, "other": {"ignored": True}}
    if answer is not None:
        content["grade"] = answer
    return {"source_guid": guid, "_state": state, "content": content}


class _Stored:
    """The two reads an export makes of a store."""

    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def list_target_files(self, action: str) -> list[str]:
        return ["part-00000.json"]

    def read_target(self, action: str, relative_path: str) -> list[dict]:
        return self._records


def test_a_record_makes_a_row_of_identity_carried_and_answered_fields():
    records = [_record("g1", {"score": 4, "note": "fine"}, source={"id": 7, "body": "long"})]

    assert output_table(records, "grade", ["id"]) == (
        ["source_guid", "id", "score", "note"],
        [("g1", 7, 4, "fine")],
    )


def test_a_field_only_some_records_answer_is_null_for_the_rest():
    records = [_record("g1", {"score": 4}), _record("g2", {"score": 2, "note": "late"})]

    columns, rows = output_table(records, "grade", [])

    assert columns == ["source_guid", "score", "note"]
    assert rows == [("g1", 4, None), ("g2", 2, "late")]


def test_a_nested_field_is_written_as_json_text():
    records = [_record("g1", {"tags": ["b", "a"], "detail": {"z": 1, "a": 2}})]

    _, rows = output_table(records, "grade", [])

    assert rows == [("g1", '["b", "a"]', '{"a": 2, "z": 1}')]


@pytest.mark.parametrize("state", ["guard_skipped", "cascade_skipped", "failed"])
def test_a_record_the_action_did_not_answer_makes_no_row(state):
    records = [_record("g1", {"score": 4}, state=state), _record("g2", None)]

    assert output_table(records, "grade", [])[1] == []


def test_an_answered_field_named_like_a_carried_column_is_refused():
    records = [_record("g1", {"id": "theirs"}, source={"id": 7})]

    with pytest.raises(ConfigurationError, match="named like a column written beside its own: id"):
        output_table(records, "grade", ["id"])


@pytest.fixture
def connector(tmp_path):
    with SqliteConnector(tmp_path / "warehouse.db") as connector:
        yield connector


def _output(**settings) -> OutputConfig:
    return OutputConfig(action="grade", connection="warehouse", table="grades", **settings)


def _held(connector) -> list[dict]:
    return list(connector.read("SELECT * FROM grades ORDER BY score"))


def test_an_output_merges_on_the_record_identity_unless_told_otherwise(connector):
    store = _Stored([_record("g1", {"score": 4}), _record("g2", {"score": 2})])

    assert [write_output(store, _output(), connector) for _ in range(2)] == [2, 2]
    assert _held(connector) == [
        {"source_guid": "g2", "score": 2},
        {"source_guid": "g1", "score": 4},
    ]


@pytest.mark.parametrize("mode", [WriteMode.MERGE, WriteMode.APPEND])
def test_two_records_sharing_a_key_are_refused_before_a_row_is_written(connector, mode):
    # An expansion stores several records under one source_guid, the default key.
    store = _Stored([_record("g1", {"item": "a"}), _record("g1", {"item": "b"})])

    with pytest.raises(ConfigurationError, match="Two records of grade share the key of grades"):
        write_output(store, _output(mode=mode), connector)

    assert list(connector.read("SELECT name FROM sqlite_master WHERE name = 'grades'")) == []


def test_a_key_that_tells_the_records_apart_writes_them_all(connector):
    store = _Stored(
        [
            _record("g1", {"item": "a"}, source={"id": 1}),
            _record("g1", {"item": "b"}, source={"id": 2}),
        ]
    )

    assert write_output(store, _output(carry=["id"], key=["id"]), connector) == 2


def test_a_record_stored_twice_alike_is_written_once(connector):
    store = _Stored([_record("g1", {"score": 4}), _record("g1", {"score": 4})])

    assert write_output(store, _output(), connector) == 1
    assert _held(connector) == [{"source_guid": "g1", "score": 4}]


def test_a_replace_writes_every_record_of_a_shared_key(connector):
    store = _Stored([_record("g1", {"item": "a"}), _record("g1", {"item": "b"})])

    assert write_output(store, _output(mode=WriteMode.REPLACE), connector) == 2


def test_a_key_the_rows_do_not_hold_is_refused(connector):
    store = _Stored([_record("g1", {"score": 4})])

    with pytest.raises(ConfigurationError, match="key of grades names id"):
        write_output(store, _output(key=["id"]), connector)


def test_no_records_leaves_an_appended_table_untouched_and_empties_a_replaced_one(connector):
    write_output(_Stored([_record("g1", {"score": 4})]), _output(), connector)

    assert write_output(_Stored([]), _output(mode=WriteMode.APPEND), connector) == 0
    assert len(_held(connector)) == 1

    assert write_output(_Stored([]), _output(mode=WriteMode.REPLACE), connector) == 0
    assert _held(connector) == []


def test_a_column_takes_the_type_its_values_share():
    columns = ["whole", "mixed", "flag", "words", "empty", "odd"]
    rows = [(1, 1, True, "a", None, 1), (None, 2.5, False, "b", None, "x")]

    assert column_types(columns, rows) == {
        "whole": ColumnType.INTEGER,
        "mixed": ColumnType.REAL,
        "flag": ColumnType.BOOLEAN,
        "words": ColumnType.TEXT,
        "empty": ColumnType.TEXT,
        "odd": ColumnType.TEXT,
    }


def test_the_table_an_output_creates_is_typed_by_its_values(connector):
    store = _Stored([_record("g1", {"score": 4, "ratio": 0.5, "passed": True})])

    write_output(store, _output(), connector)

    declared = {
        row["name"]: row["type"]
        for row in connector.read("SELECT name, type FROM pragma_table_info('grades')")
    }
    assert declared == {
        "source_guid": "TEXT",
        "score": "INTEGER",
        "ratio": "REAL",
        "passed": "BOOLEAN",
    }


def test_an_output_naming_an_action_the_workflow_does_not_run_is_refused(tmp_path):
    declared = [{"action": "grad", "connection": "warehouse", "table": "grades"}]

    with pytest.raises(ConfigurationError, match="outputs name grad, which .* runs grade"):
        write_outputs(_Stored([]), declared, tmp_path, actions=["grade"])


@pytest.mark.parametrize(
    ("carry", "problem"),
    [(["id", "id"], "names id more than once"), (["source_guid"], "is the record's identity")],
)
def test_a_carried_column_that_would_be_written_twice_is_refused(carry, problem):
    with pytest.raises(ValueError, match=problem):
        _output(carry=carry)


@pytest.mark.parametrize("unanswered", ["guard_skipped", "failed"])
def test_a_merge_keyed_on_an_answered_field_with_nothing_answered_writes_nothing(
    unanswered, connector
):
    store = _Stored([_record("g1", {"score": 4}, state=unanswered)])

    assert write_output(store, _output(key=["score"]), connector) == 0
    assert list(connector.read("SELECT name FROM sqlite_master WHERE name = 'grades'")) == []


def test_a_carried_field_no_record_s_source_holds_is_refused():
    records = [_record("g1", {"score": 4}, source={"ticket_id": 7})]

    with pytest.raises(
        ConfigurationError, match=r"'carry' names ticket, which no record's source"
    ):
        output_table(records, "grade", ["ticket"])


def test_a_carried_field_only_some_sources_hold_is_null_for_the_rest():
    records = [
        _record("g1", {"score": 4}, source={"ticket": 7}),
        _record("g2", {"score": 2}, source={}),
    ]

    assert output_table(records, "grade", ["ticket"])[1] == [("g1", 7, 4), ("g2", None, 2)]


def test_writing_one_action_s_output_when_none_writes_it_is_refused(tmp_path):
    declared = [{"action": "grade", "connection": "warehouse", "table": "grades"}]

    with pytest.raises(
        ConfigurationError, match="No output writes grad; the actions with outputs"
    ):
        write_outputs(_Stored([]), declared, tmp_path, actions=["grade"], only_action="grad")


def test_an_append_output_written_twice_adds_each_record_once(connector):
    store = _Stored([_record("g1", {"score": 4}), _record("g2", {"score": 2})])

    assert write_output(store, _output(mode=WriteMode.APPEND), connector) == 2
    assert write_output(store, _output(mode=WriteMode.APPEND), connector) == 0
    assert len(_held(connector)) == 2

    store = _Stored([_record("g1", {"score": 4}), _record("g3", {"score": 5})])
    assert write_output(store, _output(mode=WriteMode.APPEND), connector) == 1
    assert len(_held(connector)) == 3


def test_keys_that_read_the_same_as_text_are_one_key(connector):
    # The write compares keys as text, so 7 and "7" would be the same row twice.
    store = _Stored(
        [
            _record("g1", {"score": 1}, source={"id": 7}),
            _record("g2", {"score": 2}, source={"id": "7"}),
        ]
    )

    with pytest.raises(ConfigurationError, match="share the key of grades"):
        write_output(store, _output(carry=["id"], key=["id"]), connector)


def test_an_answered_field_named_like_a_carried_column_in_another_case_is_refused():
    records = [_record("g1", {"ID": "theirs"}, source={"id": 7})]

    with pytest.raises(ConfigurationError, match="named like a column written beside its own: ID"):
        output_table(records, "grade", ["id"])


def test_two_answered_fields_that_differ_only_in_case_are_refused():
    records = [_record("g1", {"summary": "a"}), _record("g2", {"Summary": "b"})]

    with pytest.raises(ConfigurationError, match="writes both 'summary' and 'Summary'"):
        output_table(records, "grade", [])

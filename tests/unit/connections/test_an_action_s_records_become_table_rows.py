"""An output is one row a record: its identity, carried source fields, the action's fields."""

import pytest

from agent_actions.config.schema import OutputConfig
from agent_actions.connections import WriteMode
from agent_actions.connections.export import output_table, write_output
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

    with pytest.raises(ConfigurationError, match="named like a carried column: id"):
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


def test_two_records_sharing_a_key_leave_the_last_one_stored(connector):
    store = _Stored(
        [
            _record("old", {"score": 1}, source={"id": 7}),
            _record("new", {"score": 5}, source={"id": 7}),
        ]
    )

    write_output(store, _output(carry=["id"], key=["id"]), connector)

    assert _held(connector) == [{"source_guid": "new", "id": 7, "score": 5}]


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

"""An output that cannot be written is refused before any action runs.

A missing driver, a name that is not a table or column name, or two outputs
writing one table were found only after every model call was paid for, or not
at all: two outputs merging into one table deleted each other's rows.
"""

import sys

import pytest

from agent_actions.connections.export import check_outputs, write_outputs
from agent_actions.errors import ConfigurationError


def _project(tmp_path, connections: str):
    (tmp_path / "agent_actions.yml").write_text(f"connections:\n{connections}")
    return tmp_path


SQLITE = "  warehouse:\n    type: sqlite\n    path: w.db\n"


def _output(**settings) -> dict:
    return {"action": "grade", "connection": "warehouse", "table": "grades", **settings}


def test_a_connection_whose_driver_is_not_installed_is_refused(tmp_path, monkeypatch):
    root = _project(tmp_path, "  warehouse:\n    type: redshift\n    host: h\n    database: d\n")
    monkeypatch.setitem(sys.modules, "redshift_connector", None)
    monkeypatch.delitem(sys.modules, "agent_actions.connections.redshift", raising=False)

    with pytest.raises(ConfigurationError, match=r"agent-actions\[redshift\]"):
        check_outputs([_output()], root, actions=["grade"])


@pytest.mark.parametrize(
    "settings",
    [{"table": "ticket-results"}, {"key": ["ticket id"]}, {"carry": ["id;drop"]}],
)
def test_a_name_that_is_not_a_table_or_column_name_is_refused(tmp_path, settings):
    root = _project(tmp_path, SQLITE)

    with pytest.raises(ConfigurationError, match="is not a table or column name"):
        check_outputs([_output(**settings)], root, actions=["grade"])


def test_two_outputs_writing_one_table_are_refused(tmp_path):
    root = _project(tmp_path, SQLITE)
    outputs = [_output(), _output(action="route", table="GRADES")]

    with pytest.raises(ConfigurationError, match="Both grade and route write GRADES"):
        check_outputs(outputs, root, actions=["grade", "route"])


class _Stored:
    def __init__(self, records):
        self._records = records

    def list_target_files(self, action):
        return ["part-00000.json"]

    def read_target(self, action, relative_path):
        return [r for r in self._records if action in r["content"]]


def test_one_table_name_on_two_connections_is_counted_apart(tmp_path):
    root = _project(tmp_path, SQLITE + "  archive:\n    type: sqlite\n    path: a.db\n")
    record = {"source_guid": "g1", "_state": "active", "content": {"grade": {"score": 4}}}
    outputs = [_output(), _output(connection="archive")]

    written = write_outputs(_Stored([record]), outputs, root, actions=["grade"])

    assert written == {"grades on warehouse": 1, "grades on archive": 1}

"""``agac records`` prints an action's stored records, and failed records' inputs, as JSON.

The store keeps these payloads compressed, so this command replaces reading them with sqlite3.
"""

import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

WORKFLOW = "wf"
ACTION = "summarize"


def _record(n: int, action: str = ACTION) -> dict:
    """A row as the pipeline stores it, lifecycle fields included."""
    return {
        "source_guid": f"guid-{n}",
        "target_id": f"tid-{n}-{action}",
        "node_id": f"{action}_node",
        "lineage": [],
        "metadata": {},
        "_state": "processed",
        "_state_history": [],
        "_state_schema_version": 1,
        "content": {action: {"summary": f"Page {n} in one sentence."}},
    }


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    workflow = tmp_path / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(f"name: {WORKFLOW}\nactions: []\n")
    store = workflow / "agent_io" / "store"
    store.mkdir(parents=True)
    backend = SQLiteBackend(str(store / f"{WORKFLOW}.db"), workflow_name=WORKFLOW)
    backend.initialize()
    backend.write_target(ACTION, "a.json", [_record(0), _record(1)], force_full=True)
    backend.write_target(ACTION, "b.json", [_record(2)], force_full=True)
    backend.write_target("classify", "a.json", [_record(0, "classify")], force_full=True)
    backend.set_disposition(
        ACTION,
        "guid-9",
        "failed",
        reason="boom",
        relative_path="a.json",
        input_snapshot=json.dumps({"source_guid": "guid-9", "content": {"page": "nine"}}),
    )
    backend.set_disposition(ACTION, "guid-0", "success", relative_path="a.json")
    backend.close()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _records(*args):
    return CliRunner().invoke(cli, ["records", "-w", WORKFLOW, *args])


def test_an_actions_records_print_as_json(project):
    result = _records("-a", ACTION)

    assert result.exit_code == 0, result.output
    records = json.loads(result.output)
    assert [r["source_guid"] for r in records] == ["guid-0", "guid-1", "guid-2"]
    assert [r["_file"] for r in records] == ["a.json", "a.json", "b.json"]
    assert {r["_action"] for r in records} == {ACTION}
    assert records[2]["content"][ACTION]["summary"] == "Page 2 in one sentence."


def test_every_action_prints_when_none_is_named(project):
    result = _records()

    assert result.exit_code == 0, result.output
    records = json.loads(result.output)
    assert sorted((r["_action"], r["source_guid"]) for r in records) == [
        ("classify", "guid-0"),
        (ACTION, "guid-0"),
        (ACTION, "guid-1"),
        (ACTION, "guid-2"),
    ]


def test_a_source_guid_selects_that_record_in_every_action(project):
    result = _records("--source-guid", "guid-0")

    assert result.exit_code == 0, result.output
    records = json.loads(result.output)
    assert sorted(r["_action"] for r in records) == ["classify", ACTION]
    assert {r["source_guid"] for r in records} == {"guid-0"}


def test_a_file_selects_that_files_records(project):
    result = _records("-a", ACTION, "--file", "b.json")

    assert result.exit_code == 0, result.output
    assert [r["source_guid"] for r in json.loads(result.output)] == ["guid-2"]


def test_a_field_prints_one_value_per_record(project):
    result = _records("-a", ACTION, "--field", f"content.{ACTION}.summary")

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        "Page 0 in one sentence.",
        "Page 1 in one sentence.",
        "Page 2 in one sentence.",
    ]

    actions = _records("--source-guid", "guid-0", "--field", "_action")
    assert sorted(json.loads(actions.output)) == ["classify", ACTION]

    missing = _records("-a", ACTION, "--field", "content.nothing.here")
    assert json.loads(missing.output) == [None, None, None]


def test_snapshots_print_the_input_each_failed_record_was_processed_with(project):
    result = _records("--snapshots")

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        {
            "_action": ACTION,
            "record_id": "guid-9",
            "disposition": "failed",
            "reason": "boom",
            "relative_path": "a.json",
            "input_snapshot": {"source_guid": "guid-9", "content": {"page": "nine"}},
        }
    ]


def test_an_action_with_no_records_says_so(project):
    result = _records("-a", "nothing")

    assert result.exit_code != 0
    assert "No stored records for action 'nothing'" in result.output


def test_a_workflow_with_no_store_says_so(project):
    result = CliRunner().invoke(cli, ["records", "-w", "other"])

    assert result.exit_code != 0
    assert "No store for workflow 'other'" in result.output

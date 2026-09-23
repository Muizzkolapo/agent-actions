"""A batch JSON document that holds one object rather than a list of them."""

import json

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_batch_data,
    _prepare_online_data,
    _save_source_data,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

PAYLOAD = {"ticket_id": "T-001", "text": "Server is down"}


def _staged(content, mode="batch", file_path="/tmp/doc.json"):
    ctx = DataPreparationContext(
        content=content,
        file_type=".json",
        agent_config={"run_mode": mode},
        file_path=file_path,
        agent_name="extract",
        idx=0,
    )
    prepare = _prepare_batch_data if mode == "batch" else _prepare_online_data
    rows, _ = prepare(ctx)
    return rows


def _workflow(tmp_path):
    staging = tmp_path / "wf" / "agent_io" / "staging"
    staging.mkdir(parents=True)
    doc = staging / "ticket.json"
    doc.write_text(json.dumps(PAYLOAD))
    target = tmp_path / "wf" / "agent_io" / "target" / "extract"
    target.mkdir(parents=True)
    return doc, staging, target


class TestOneObjectIsARecordLikeAnyOther:
    def test_it_is_one_record(self):
        assert len(_staged(PAYLOAD)) == 1

    def test_it_carries_an_identity(self):
        assert _staged(PAYLOAD)[0].get("source_guid")

    def test_its_identity_is_what_the_same_payload_gets_inside_a_list(self):
        assert _staged(PAYLOAD)[0]["source_guid"] == _staged([PAYLOAD])[0]["source_guid"]

    def test_its_identity_is_what_the_online_path_gives_it(self):
        online = _staged(PAYLOAD, mode="online")[0]["source_guid"]
        assert _staged(PAYLOAD)[0]["source_guid"] == online

    def test_its_payload_sits_where_every_other_row_puts_it(self):
        assert _staged(PAYLOAD)[0]["content"] == {"source": PAYLOAD}

    def test_it_carries_the_fields_a_list_row_carries(self):
        assert set(_staged(PAYLOAD)[0]) == set(_staged([PAYLOAD])[0])

    def test_it_belongs_to_the_node_that_staged_it(self):
        assert _staged(PAYLOAD)[0]["node_id"].startswith("node_0_")

    def test_it_is_its_own_root(self):
        row = _staged(PAYLOAD)[0]
        assert row["parent_target_id"] is None
        assert row["root_target_id"] == row["target_id"]


class TestTheStoreCanSeeIt:
    def test_its_source_row_is_written(self, tmp_path):
        doc, staging, target = _workflow(tmp_path)
        backend = SQLiteBackend(str(tmp_path / "s.db"), "wf")
        backend.initialize()
        rows = _staged(PAYLOAD, file_path=str(doc))
        _save_source_data([], rows, str(doc), str(staging), str(target), storage_backend=backend)
        stored = backend.read_source("ticket")
        backend.close()
        assert [row["content"]["source"] for row in stored] == [PAYLOAD]

    def test_its_stored_row_keeps_the_identity_it_was_staged_with(self, tmp_path):
        doc, staging, target = _workflow(tmp_path)
        backend = SQLiteBackend(str(tmp_path / "s.db"), "wf")
        backend.initialize()
        rows = _staged(PAYLOAD, file_path=str(doc))
        _save_source_data([], rows, str(doc), str(staging), str(target), storage_backend=backend)
        stored = backend.read_source("ticket")
        backend.close()
        assert [row["source_guid"] for row in stored] == [rows[0]["source_guid"]]


class TestADocumentThatIsNotRecords:
    def test_a_bare_value_is_refused(self):
        with pytest.raises(AgentActionsError):
            _staged(42)

    def test_the_refusal_names_the_shape_it_found(self):
        with pytest.raises(AgentActionsError) as caught:
            _staged(42)
        assert "int" in str(caught.value)

    def test_the_refusal_names_the_file_it_read(self):
        with pytest.raises(AgentActionsError) as caught:
            _staged(42, file_path="/tmp/ticket.json")
        assert caught.value.context["file_path"] == "/tmp/ticket.json"

    def test_a_list_whose_rows_are_bare_values_is_refused(self):
        with pytest.raises(AgentActionsError):
            _staged([1, 2])

    def test_the_refusal_names_the_row_it_stopped_on(self):
        with pytest.raises(AgentActionsError) as caught:
            _staged([PAYLOAD, "not a record"])
        assert caught.value.context["row_index"] == 1

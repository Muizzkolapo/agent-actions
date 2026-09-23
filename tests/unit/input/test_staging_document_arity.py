"""A staging document is a list of records; a lone object is refused."""

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
SECOND = {"ticket_id": "T-002", "text": "Cannot login"}


def _staged(tmp_path, document, mode="batch", name="doc.json"):
    doc = tmp_path / name
    doc.write_text(json.dumps(document))
    return _prepare(json.loads(doc.read_text()), mode, str(doc))


def _prepare(content, mode, file_path):
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


@pytest.mark.parametrize("mode", ["batch", "online"])
class TestALoneObjectIsRefused:
    def test_it_does_not_stage(self, tmp_path, mode):
        with pytest.raises(AgentActionsError):
            _staged(tmp_path, PAYLOAD, mode=mode)

    def test_the_refusal_says_to_wrap_it_in_an_array(self, tmp_path, mode):
        with pytest.raises(AgentActionsError) as caught:
            _staged(tmp_path, PAYLOAD, mode=mode)
        assert "Wrap it in an array" in str(caught.value)

    def test_the_refusal_names_the_file_it_read(self, tmp_path, mode):
        with pytest.raises(AgentActionsError) as caught:
            _staged(tmp_path, PAYLOAD, mode=mode, name="tickets.json")
        assert caught.value.context["file_path"] == str(tmp_path / "tickets.json")

    def test_the_refusal_names_the_shape_it_found(self, tmp_path, mode):
        with pytest.raises(AgentActionsError) as caught:
            _staged(tmp_path, PAYLOAD, mode=mode)
        assert caught.value.context["content_type"] == "dict"

    def test_a_bare_value_is_refused_as_a_document_not_as_a_row(self, tmp_path, mode):
        with pytest.raises(AgentActionsError) as caught:
            _staged(tmp_path, 42, mode=mode)
        assert caught.value.context["content_type"] == "int"
        assert "row_index" not in caught.value.context


@pytest.mark.parametrize("mode", ["batch", "online"])
class TestAListOfRecordsIsUnaffected:
    def test_every_row_keeps_its_payload(self, tmp_path, mode):
        rows = _staged(tmp_path, [PAYLOAD, SECOND], mode=mode)
        assert [row["content"]["source"] for row in rows] == [PAYLOAD, SECOND]

    def test_a_one_row_document_is_one_record(self, tmp_path, mode):
        assert len(_staged(tmp_path, [PAYLOAD], mode=mode)) == 1

    def test_a_one_row_document_carries_an_identity(self, tmp_path, mode):
        assert _staged(tmp_path, [PAYLOAD], mode=mode)[0]["source_guid"]

    def test_an_empty_document_stages_nothing(self, tmp_path, mode):
        assert _staged(tmp_path, [], mode=mode) == []

    def test_a_row_that_is_not_an_object_is_still_refused_by_row(self, tmp_path, mode):
        with pytest.raises(AgentActionsError) as caught:
            _staged(tmp_path, [PAYLOAD, "not a record"], mode=mode)
        assert caught.value.context["row_index"] == 1
        assert caught.value.context["row_type"] == "str"


class TestABatchRowKeepsItsAncestry:
    def test_a_one_row_document_is_its_own_root(self, tmp_path):
        row = _staged(tmp_path, [PAYLOAD])[0]
        assert row["parent_target_id"] is None
        assert row["root_target_id"] == row["target_id"]

    def test_every_row_belongs_to_the_node_that_staged_it(self, tmp_path):
        rows = _staged(tmp_path, [PAYLOAD, SECOND])
        assert {row["node_id"] for row in rows} == {rows[0]["node_id"]}
        assert rows[0]["node_id"].startswith("node_0_")


class TestBatchAndOnlineAgree:
    def test_they_derive_the_same_identity_for_the_same_payload(self, tmp_path):
        assert (
            _staged(tmp_path, [PAYLOAD], mode="batch")[0]["source_guid"]
            == _staged(tmp_path, [PAYLOAD], mode="online")[0]["source_guid"]
        )

    def test_they_refuse_a_lone_object_with_the_same_message(self, tmp_path):
        messages = []
        for mode in ("batch", "online"):
            with pytest.raises(AgentActionsError) as caught:
                _staged(tmp_path, PAYLOAD, mode=mode)
            messages.append(str(caught.value))
        assert messages[0] == messages[1]


class TestTheStoreCanSeeAOneRowDocument:
    def _workflow(self, tmp_path):
        staging = tmp_path / "wf" / "agent_io" / "staging"
        staging.mkdir(parents=True)
        doc = staging / "ticket.json"
        doc.write_text(json.dumps([PAYLOAD]))
        target = tmp_path / "wf" / "agent_io" / "target" / "extract"
        target.mkdir(parents=True)
        return doc, staging, target

    def test_its_source_row_is_written(self, tmp_path):
        doc, staging, target = self._workflow(tmp_path)
        backend = SQLiteBackend(str(tmp_path / "s.db"), "wf")
        backend.initialize()
        rows = _prepare([PAYLOAD], "batch", str(doc))
        _save_source_data([], rows, str(doc), str(staging), str(target), storage_backend=backend)
        stored = backend.read_source("ticket")
        backend.close()
        assert [row["content"]["source"] for row in stored] == [PAYLOAD]

    def test_its_stored_row_keeps_the_identity_it_was_staged_with(self, tmp_path):
        doc, staging, target = self._workflow(tmp_path)
        backend = SQLiteBackend(str(tmp_path / "s.db"), "wf")
        backend.initialize()
        rows = _prepare([PAYLOAD], "batch", str(doc))
        _save_source_data([], rows, str(doc), str(staging), str(target), storage_backend=backend)
        stored = backend.read_source("ticket")
        backend.close()
        assert [row["source_guid"] for row in stored] == [rows[0]["source_guid"]]

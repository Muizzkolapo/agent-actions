"""An online JSON input whose rows are not objects."""

import json

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_online_data,
)


def _staged(document, tmp_path):
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps(document))
    ctx = DataPreparationContext(
        content=json.loads(doc.read_text()),
        file_type=".json",
        agent_config={},
        file_path=str(doc),
        agent_name="extract",
        idx=0,
    )
    rows, _ = _prepare_online_data(ctx)
    return rows


class TestARowThatCannotCarryAPayload:
    def test_a_bare_value_is_refused(self, tmp_path):
        with pytest.raises(AgentActionsError):
            _staged(42, tmp_path)

    def test_a_list_of_bare_values_is_refused(self, tmp_path):
        with pytest.raises(AgentActionsError):
            _staged([1, 2], tmp_path)

    def test_the_refusal_names_the_row_it_stopped_on(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _staged([{"a": 1}, "not a record"], tmp_path)
        assert caught.value.context["row_index"] == 1
        assert caught.value.context["row_type"] == "str"

    def test_the_refusal_names_the_file_it_read(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _staged(42, tmp_path)
        assert caught.value.context["file_path"] == str(tmp_path / "doc.json")

    def test_it_reads_the_same_as_the_batch_refusal(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _staged(42, tmp_path)
        assert "A staged row must be an object; found int" in str(caught.value)


class TestRecordsStillStage:
    def test_an_object_document_is_one_enveloped_record(self, tmp_path):
        rows = _staged({"a": 1}, tmp_path)
        assert [row["content"] for row in rows] == [{"source": {"a": 1}}]
        assert rows[0]["source_guid"]

    def test_a_list_of_objects_keeps_every_row(self, tmp_path):
        rows = _staged([{"a": 1}, {"b": 2}], tmp_path)
        assert [row["content"]["source"] for row in rows] == [{"a": 1}, {"b": 2}]

"""Rows staged from a spreadsheet, in both modes."""

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_batch_data,
    _prepare_online_data,
)

SHEET = [{"id": 1, "title": "first"}, {"id": 2, "title": "second"}]


def _staged(content, mode):
    ctx = DataPreparationContext(
        content=content,
        file_type=".xlsx",
        agent_config={"run_mode": mode},
        file_path="/tmp/book.xlsx",
        agent_name="extract",
        idx=0,
    )
    rows, _ = (_prepare_batch_data if mode == "batch" else _prepare_online_data)(ctx)
    return rows


@pytest.mark.parametrize("mode", ["batch", "online"])
class TestASheetOfRecords:
    def test_every_row_is_enveloped(self, mode):
        assert [row["content"]["source"] for row in _staged(SHEET, mode)] == SHEET

    def test_every_row_carries_an_identity(self, mode):
        assert all(row["source_guid"] for row in _staged(SHEET, mode))

    def test_rows_keep_their_order(self, mode):
        assert [row["content"]["source"]["id"] for row in _staged(SHEET, mode)] == [1, 2]

    def test_an_empty_sheet_stages_nothing(self, mode):
        assert _staged([], mode) == []


@pytest.mark.parametrize("mode", ["batch", "online"])
class TestContentThatIsNotRows:
    def test_a_bare_mapping_is_refused(self, mode):
        with pytest.raises(AgentActionsError) as caught:
            _staged({"id": 1, "title": "first"}, mode)
        # Refused as content that is not rows, not as a row whose key is a string.
        assert caught.value.context["content_type"] == "dict"
        assert "A staged input must be rows; found dict" in str(caught.value)

    def test_a_row_that_is_not_a_record_is_refused(self, mode):
        with pytest.raises(AgentActionsError):
            _staged([{"id": 1}, "not a record"], mode)

    def test_the_refusal_reads_the_same_as_the_json_one(self, mode):
        with pytest.raises(AgentActionsError) as caught:
            _staged([{"id": 1}, 7], mode)
        assert "A staged row must be an object; found int" in str(caught.value)
        assert caught.value.context["row_index"] == 1

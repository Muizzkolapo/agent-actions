"""Tests for TrackedItem — hidden provenance for FILE mode tools."""

import pytest

from agent_actions.record.tracking import TrackedItem
from agent_actions.utils.udf_management.registry import FileUDFResult


class TestTrackedItem:
    def test_acts_as_dict(self):
        item = TrackedItem({"q": "test"}, source_index=0)
        assert item["q"] == "test"

    def test_source_index_hidden(self):
        item = TrackedItem({"q": "test"}, source_index=3)
        assert item._source_index == 3
        assert "source_index" not in item
        assert "_source_index" not in item

    def test_survives_modification(self):
        item = TrackedItem({"q": "test"}, source_index=3)
        item["q"] = "modified"
        item["new"] = "added"
        assert item._source_index == 3

    def test_spread_loses_provenance(self):
        item = TrackedItem({"q": "test"}, source_index=3)
        spread = {**item}
        assert not isinstance(spread, TrackedItem)
        assert not hasattr(spread, "_source_index")

    def test_iteration_works(self):
        item = TrackedItem({"a": 1, "b": 2}, source_index=0)
        assert list(item.keys()) == ["a", "b"]
        assert list(item.values()) == [1, 2]

    def test_len_works(self):
        item = TrackedItem({"a": 1, "b": 2}, source_index=0)
        assert len(item) == 2

    def test_del_works(self):
        item = TrackedItem({"a": 1, "b": 2}, source_index=0)
        del item["a"]
        assert "a" not in item
        assert item._source_index == 0

    def test_copy_returns_plain_dict(self):
        item = TrackedItem({"q": "test"}, source_index=3)
        copied = item.copy()
        # dict.copy() returns a plain dict, not TrackedItem
        assert isinstance(copied, dict)
        assert not hasattr(copied, "_source_index")

    def test_is_dict_subclass(self):
        item = TrackedItem({"q": "test"}, source_index=0)
        assert isinstance(item, dict)

    def test_empty_data(self):
        item = TrackedItem({}, source_index=5)
        assert len(item) == 0
        assert item._source_index == 5


class TestFileUDFResultValidation:
    def test_valid_outputs(self):
        result = FileUDFResult(
            outputs=[
                {"source_index": 0, "data": {"q": "Q1"}},
                {"source_index": 1, "data": {"q": "Q2"}},
            ]
        )
        assert len(result.outputs) == 2

    def test_missing_source_index_raises(self):
        with pytest.raises(ValueError, match="missing 'source_index'"):
            FileUDFResult(outputs=[{"data": {"q": "Q1"}}])

    def test_missing_data_raises(self):
        with pytest.raises(ValueError, match="missing 'data' dict"):
            FileUDFResult(outputs=[{"source_index": 0}])

    def test_non_dict_data_raises(self):
        with pytest.raises(ValueError, match="missing 'data' dict"):
            FileUDFResult(outputs=[{"source_index": 0, "data": "a string"}])

    def test_non_dict_output_raises(self):
        with pytest.raises(ValueError, match="must be a dict"):
            FileUDFResult(outputs=["not a dict"])

    def test_empty_outputs_allowed(self):
        result = FileUDFResult(outputs=[])
        assert len(result.outputs) == 0

    def test_list_source_index_allowed(self):
        result = FileUDFResult(
            outputs=[
                {"source_index": [0, 1], "data": {"merged": True}},
            ]
        )
        assert result.outputs[0]["source_index"] == [0, 1]

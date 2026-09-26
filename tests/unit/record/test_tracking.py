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

    def test_empty_source_index_list_is_refused(self):
        """An empty contributor list says no input produced the row — which is what
        `None` already says, per this class's own missing-source_index message. Accepted,
        it reached `reconcile_outputs` and raised `IndexError` on a bare `src_idx[0]`.
        """
        with pytest.raises(ValueError) as caught:
            FileUDFResult(outputs=[{"source_index": [], "data": {"q": "Q1"}}])

        message = str(caught.value)
        assert "output[0]" in message, message
        assert "empty list" in message, (
            f"the refusal has to name what was wrong with the input, or it reads as the "
            f"missing-source_index error and misdiagnoses it: {message}"
        )
        assert "None" in message, (
            f"the refusal has to name the way to say a row had no input, or the author "
            f"retries with the same empty list: {message}"
        )

    def test_the_refusal_names_which_output_carried_it(self):
        """A tool returns many rows at once; a refusal that does not say which one
        sends the author reading all of them."""
        with pytest.raises(ValueError, match=r"output\[2\]"):
            FileUDFResult(
                outputs=[
                    {"source_index": 0, "data": {"q": "Q1"}},
                    {"source_index": [0, 1], "data": {"merged": True}},
                    {"source_index": [], "data": {"q": "Q3"}},
                ]
            )

    def test_none_is_still_how_a_row_says_no_input_produced_it(self):
        """Control: the refusal must not catch the documented synthetic form, which is
        the one it tells the author to use."""
        result = FileUDFResult(outputs=[{"source_index": None, "data": {"q": "Q1"}}])

        assert result.outputs[0]["source_index"] is None

    @pytest.mark.parametrize(
        ("source_index", "shown"),
        [
            ([None], "got [None]"),
            ([None, 0], "got [None]"),
            ([True], "got [True]"),
            (True, "got True"),
            (False, "got False"),
            (["0"], "got ['0']"),
            ([1.0], "got [1.0]"),
            ([-1], "got [-1]"),
            (-1, "got -1"),
            ([[0, 1]], "got [[0, 1]]"),
            ([(0,)], "got [(0,)]"),
        ],
        ids=[
            "none-in-a-list",
            "none-before-a-real-position",
            "bool-in-a-list",
            "bool-scalar",
            "false-scalar",
            "string-digit",
            "float",
            "negative",
            "negative-scalar",
            "a-list-of-positions-double-wrapped",
            "a-tuple-of-positions",
        ],
    )
    def test_a_position_that_cannot_be_one_is_refused(self, source_index, shown):
        """The bools were the silent ones: `True` is an int to `isinstance`, so the row
        took input 1's `source_guid` outright. A `None` in a list got as far as lineage
        enrichment and died there on a `<` against an int. The last two cases are
        unreachable through any pool; they pin the allowlist against being rewritten as a
        denylist, which would pass a double-wrapped index list through to `IndexError`.
        `shown` is the rendered offender because the message's own guidance says "None".
        """
        with pytest.raises(ValueError) as caught:
            FileUDFResult(outputs=[{"source_index": source_index, "data": {"q": "Q1"}}])

        message = str(caught.value)
        assert "output[0]" in message, message
        assert shown in message, f"the refusal has to show what it objected to: {message}"

    def test_an_index_past_the_end_is_left_to_the_run(self):
        """Control, and this check's boundary: how many inputs there are is not knowable
        here, and the run already handles an unresolvable contributor by accounting for
        nobody — so range stays a runtime concern while type and sign do not."""
        result = FileUDFResult(outputs=[{"source_index": [0, 99], "data": {"q": "Q1"}}])

        assert result.outputs[0]["source_index"] == [0, 99]

    def test_zero_is_not_mistaken_for_a_missing_position(self):
        """Control: 0 is falsy and is the commonest real position."""
        result = FileUDFResult(outputs=[{"source_index": 0, "data": {"q": "Q1"}}])

        assert result.outputs[0]["source_index"] == 0

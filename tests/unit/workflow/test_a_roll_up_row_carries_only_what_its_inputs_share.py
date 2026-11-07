"""A roll-up row (`source_index: None`) carries only what every input of its file shares.

It used to be built from the first input, so a reader below got row 1's `source`, row
1's per-record fields and row 1's state history as if the roll-up were that record. Now
each upstream namespace keeps the fields whose value is equal on every input; a
namespace with none is left off; row 1's tracking fields stay, since correlation ids are
derived from them and the identity is re-minted; row 1's history does not.
"""

from __future__ import annotations

from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.pipeline_file_mode import reconcile_outputs

ACTION = "roll_up"


def _inputs() -> list[dict]:
    return [
        {
            "source_guid": "g1",
            "parent_source_guid": "p1",
            "version_correlation_id": "c1",
            "_state_history": [{"state": "ok", "action": "up"}],
            "content": {
                "source": {"id": "row-a", "lang": "en"},
                "up": {"shared": "same", "own": "first"},
            },
        },
        {
            "source_guid": "g2",
            "parent_source_guid": "p2",
            "version_correlation_id": "c2",
            "_state_history": [{"state": "ok", "action": "up"}],
            "content": {
                "source": {"id": "row-b", "lang": "en"},
                "up": {"shared": "same", "own": "second"},
            },
        },
    ]


def _roll_up(inputs: list[dict]) -> dict:
    rows, mapping = reconcile_outputs(
        FileUDFResult([{"source_index": None, "data": {"note": "rolled"}}]), ACTION, inputs
    )
    assert mapping == {0: None}
    (row,) = rows
    return row


class TestWhatTheRowCarries:
    def test_only_the_fields_equal_on_every_input(self):
        row = _roll_up(_inputs())

        assert row["content"]["up"] == {"shared": "same"}
        assert row["content"]["source"] == {"lang": "en"}
        assert row["content"][ACTION] == {"note": "rolled"}

    def test_a_namespace_with_no_shared_field_is_left_off(self):
        inputs = _inputs()
        inputs[1]["content"]["source"]["lang"] = "fr"

        row = _roll_up(inputs)

        assert "source" not in row["content"]
        assert sorted(row["content"]) == [ACTION, "up"]

    def test_the_first_inputs_history_is_not_the_rows(self):
        row = _roll_up(_inputs())

        assert not row.get("_state_history")

    def test_the_shared_set_is_computed_over_every_input_not_the_first_two(self):
        inputs = _inputs() + [dict(_inputs()[0], source_guid="g3")]
        inputs[2]["content"] = {"source": {"id": "row-c", "lang": "en"}, "up": {"shared": "other"}}

        row = _roll_up(inputs)

        assert "up" not in row["content"]
        assert row["content"]["source"] == {"lang": "en"}

    def test_a_namespace_missing_on_one_input_is_left_off(self):
        inputs = _inputs()
        del inputs[1]["content"]["up"]

        row = _roll_up(inputs)

        assert "up" not in row["content"]


class TestIdentityAndLineageStillFollowTheFile:
    def test_the_row_is_minted_and_marked_aggregated(self):
        row = _roll_up(_inputs())

        assert row["source_guid"] not in {"g1", "g2"}
        assert row["aggregated_by"] == ACTION
        assert row["_delta_mode"] == "full"

    def test_the_correlation_id_is_derived_from_the_first_inputs(self):
        """Control: fan-in correlation still comes from row 1's tracking fields."""
        row = _roll_up(_inputs())

        assert row["version_correlation_id"] == f"c1#{ACTION}#0"
        assert row["parent_source_guid"] == "p1"

    def test_a_one_to_one_row_still_carries_its_own_input_whole(self):
        inputs = _inputs()
        rows, _ = reconcile_outputs(
            FileUDFResult([{"source_index": 1, "data": {"note": "kept"}}]), ACTION, inputs
        )

        (row,) = rows
        assert row["content"]["up"] == {"shared": "same", "own": "second"}
        assert row["content"]["source"] == {"id": "row-b", "lang": "en"}
        assert row["source_guid"] == "g2"

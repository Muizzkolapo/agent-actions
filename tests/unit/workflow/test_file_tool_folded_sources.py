"""A FILE tool's row naming several inputs lists each but its parent in folded_sources."""

from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.pipeline_file_mode import reconcile_outputs


def _input(guid: str, **extra) -> dict:
    return {"source_guid": guid, "content": {"stage": {"id": guid}}, **extra}


def _reconcile(outputs: list[dict], inputs: list[dict]) -> list[dict]:
    rows, _ = reconcile_outputs(FileUDFResult(outputs=outputs), "fold", inputs)
    return rows


def test_a_row_naming_two_inputs_lists_the_second_as_folded_by_the_action():
    rows = _reconcile(
        [{"source_index": [0, 1], "data": {"v": 1}}, {"source_index": 2, "data": {"v": 2}}],
        [_input("a"), _input("b"), _input("c")],
    )

    assert [(r["source_guid"], r.get("folded_sources")) for r in rows] == [
        ("a", {"b": "fold"}),
        ("c", None),
    ]


def test_a_fold_of_a_fold_still_names_the_first_record():
    rows = _reconcile(
        [{"source_index": [0, 1], "data": {"v": 1}}],
        [_input("a", folded_sources={"x": "earlier"}), _input("b")],
    )

    assert rows[0]["folded_sources"] == {"x": "earlier", "b": "fold"}


def test_a_row_gathering_a_whole_split_folds_nothing():
    rows = _reconcile(
        [{"source_index": [0, 1], "data": {"v": 1}}],
        [_input("s1", parent_source_guid="P"), _input("s2", parent_source_guid="P")],
    )

    assert rows[0]["source_guid"] == "P"
    assert "folded_sources" not in rows[0]


def test_an_aggregate_row_carries_no_fold_of_the_first_input():
    rows = _reconcile(
        [{"source_index": None, "data": {"v": 1}}],
        [_input("a", folded_sources={"x": "earlier"}), _input("b")],
    )

    assert "folded_sources" not in rows[0]

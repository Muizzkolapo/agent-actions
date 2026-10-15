"""A FILE-tool row names the one input it was split from only when it was given a new identity."""

from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

INPUTS = [{"source_guid": "A"}, {"source_guid": "B"}]


def test_each_row_split_from_one_input_names_it():
    rows = [{"content": "a1"}, {"content": "a2"}]

    _reattach_source_guid(rows, {0: 0, 1: 0}, INPUTS, "act")

    assert [r["split_from_source_guid"] for r in rows] == ["A", "A"]
    assert {r["source_guid"] for r in rows}.isdisjoint({"A", "B"})


def test_a_row_that_keeps_its_inputs_identity_names_no_split():
    rows = [{"content": "a+b"}]

    _reattach_source_guid(rows, {0: [0, 1]}, INPUTS, "act")

    assert rows[0]["source_guid"] == "A"
    assert rows[0]["producer_source_guids"] == ["B"]
    assert "split_from_source_guid" not in rows[0]


def test_a_new_row_made_from_several_inputs_names_no_split():
    rows = [{"content": "a+b 1"}, {"content": "a+b 2"}]

    _reattach_source_guid(rows, {0: [0, 1], 1: [0, 1]}, INPUTS, "act")

    assert all("split_from_source_guid" not in r for r in rows)

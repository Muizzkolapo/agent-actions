"""The built-in `route` and `pick` tools, on one record's action-keyed data."""

import pytest

from agent_actions.llm.providers.tools.builtin import (
    builtin_tool,
    route_case_counts,
    run_builtin,
    runs_udf,
)

ROUTE = {"tool": "route", "field": "classify.format", "cases": ["mc", "fill"], "default": True}
PICK = {"tool": "pick", "of": ["mc_end", "fill_end"]}


def test_route_writes_the_value_when_it_is_a_case():
    assert run_builtin(ROUTE, {"classify": {"format": "fill"}}) == {"case": "fill"}


@pytest.mark.parametrize("value", ["matching", None, 3, "MC"])
def test_route_writes_default_for_any_other_value(value):
    assert run_builtin(ROUTE, {"classify": {"format": value}}) == {"case": "default"}


def test_route_with_no_default_refuses_a_value_that_is_no_case():
    with pytest.raises(ValueError, match="no case of the router"):
        run_builtin({**ROUTE, "default": False}, {"classify": {"format": "matching"}})


def test_route_reads_a_nested_field():
    spec = {**ROUTE, "field": "classify.meta.format"}

    assert run_builtin(spec, {"classify": {"meta": {"format": "mc"}}}) == {"case": "mc"}


def test_pick_writes_the_output_the_record_holds():
    data = {"source": {"x": 1}, "fill_end": {"answer": "a"}}

    assert run_builtin(PICK, data) == {"answer": "a"}


def test_pick_of_a_record_holding_no_output_writes_nothing():
    assert run_builtin(PICK, {"mc_end": None}) == {}


def test_only_a_known_built_in_is_one():
    assert builtin_tool({"_builtin": ROUTE}) == ROUTE
    assert builtin_tool({"_builtin": {"tool": "unknown"}}) is None
    assert builtin_tool({"impl": "route"}) is None


def test_a_built_in_tool_action_runs_no_udf():
    assert runs_udf({"kind": "tool", "impl": "tag"})
    assert not runs_udf({"kind": "tool", "impl": "agac.route", "_builtin": ROUTE})
    assert not runs_udf({"kind": "llm"})


def test_the_case_counts_follow_the_router_order_and_keep_a_case_with_none():
    rows = [{"content": {"router": {"case": c}}} for c in ["fill", "default", "fill"]]

    assert route_case_counts({"_builtin": ROUTE}, "router", rows) == {
        "mc": 0,
        "fill": 2,
        "default": 1,
    }
    assert route_case_counts({"_builtin": PICK}, "router", rows) is None

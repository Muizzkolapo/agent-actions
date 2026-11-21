"""What the load makes of `- route:` and `- join:` entries, and what it refuses."""

from __future__ import annotations

import copy

import pytest

from agent_actions.config.routes import expand_routes, finish_routes
from agent_actions.errors import ConfigurationError

WF = "agent_config/wf.yml"


def _action(name, **extra):
    return {"name": name, "intent": "x", "prompt": "p", "schema": {"x": "string"}, **extra}


def _workflow(route=None, *, actions=None, join=None):
    route = route if route is not None else {}
    entries = [
        _action("classify"),
        {
            "route": "router",
            True: "classify.format",
            "cases": {"a": ["on_a"], "b": ["on_b"]},
            "default": "filter",
            **route,
        },
        _action("on_a"),
        _action("on_b"),
        _action("after_a", dependencies=["on_a"]),
        *(actions or []),
    ]
    if join is not False:
        entries.append(join or {"join": "joined", "of": ["after_a", "on_b"]})
    return {"name": "wf", "actions": entries}


def _by_name(data):
    return {a["name"]: a for a in data["actions"]}


def _refusal(data):
    with pytest.raises(ConfigurationError) as caught:
        expand_routes(data, WF)
    return str(caught.value)


def test_the_router_is_a_built_in_route_tool_reading_its_field():
    router = _by_name(expand_routes(_workflow(), WF))["router"]

    assert router["kind"] == "tool"
    assert router["impl"] == "agac.route"
    assert router["dependencies"] == ["classify"]
    assert router["context_scope"] == {"observe": ["classify.format"]}
    assert router["_builtin"]["field"] == "classify.format"
    assert router["_builtin"]["cases"] == ["a", "b"]
    assert router["_builtin"]["default"] is False


def test_default_filter_is_an_ordinary_filter_at_the_router():
    router = _by_name(expand_routes(_workflow(), WF))["router"]

    assert router["guard"] == {
        "condition": 'classify.format IN ["a", "b"]',
        "on_false": "filter",
        "passthrough_on_error": False,
    }


def test_each_entry_gets_the_guard_of_its_case_and_sends_the_others_elsewhere():
    on_a = _by_name(expand_routes(_workflow(), WF))["on_a"]

    assert on_a["guard"] == {"condition": 'router.case == "a"', "on_false": "filter"}
    assert on_a["_sends_elsewhere"] is True
    assert on_a["dependencies"] == ["router"]
    assert on_a["context_scope"] == {"observe": ["router.case"]}


def test_a_default_branch_is_entered_on_the_case_default():
    data = expand_routes(_workflow({"default": ["on_other"]}, actions=[_action("on_other")]), WF)

    actions = _by_name(data)
    assert actions["on_other"]["guard"]["condition"] == 'router.case == "default"'
    assert "guard" not in actions["router"]
    assert actions["router"]["_builtin"]["default"] is True


def test_the_join_is_a_built_in_pick_that_gathers():
    joined = _by_name(expand_routes(_workflow(), WF))["joined"]

    assert joined["impl"] == "agac.pick"
    assert joined["dependencies"] == ["after_a", "on_b"]
    assert joined["context_scope"] == {"observe": ["after_a.*", "on_b.*"]}
    assert joined["_builtin"] == {"tool": "pick", "of": ["after_a", "on_b"]}
    assert joined["_gathers"] is True


def test_the_join_schema_holds_every_field_of_the_joined_actions_none_required():
    data = expand_routes(_workflow(), WF)
    actions = _by_name(data)
    actions["after_a"]["schema"] = {
        "name": "a",
        "fields": [{"id": "question", "type": "string", "expectations": [{"id": "x"}]}],
    }
    actions["on_b"]["schema"] = {"type": "object", "properties": {"blank": {"type": "string"}}}

    finish_routes(data, WF)

    assert actions["joined"]["schema"] == {
        "name": "joined_joined",
        "fields": [{"id": "question", "type": "string"}, {"id": "blank", "type": "string"}],
        "additionalProperties": True,
        "required_by_default": False,
    }


def test_a_workflow_without_a_route_is_left_as_it_is():
    data = {"name": "wf", "actions": [_action("a")]}

    assert expand_routes(data, WF) is data


@pytest.mark.parametrize(
    ("route", "message"),
    [
        ({"default": None}, "names no branch"),
        ({"cases": {"a": ["on_a"], "b": []}}, "case 'b' names no branch"),
        ({"cases": {"a": ["nowhere"]}}, "names 'nowhere', which is no action or include instance"),
        (
            {"cases": {"a": ["on_a"], "b": ["on_a"]}},
            "starts the branch of case 'a' and of case 'b'",
        ),
        ({"cases": {True: ["on_a"]}}, "case True is not a string"),
        ({"cases": {"default": ["on_a"]}}, "'default' cannot be a case"),
        ({"cases": {'say "hi"': ["on_a"]}}, "holds a quote"),
        ({"cases": {}}, "'cases:' must map each value"),
        ({True: "classify"}, "'on:' must name one field of one action"),
        ({True: "missing.format"}, "reads 'missing', which is no action"),
        ({"cases": {"a": ["classify"]}}, "the action whose field the router reads"),
        ({"when": "x"}, "unknown key when"),
        ({"route": "router_2"}, "reads as a version"),
        ({"route": "classify"}, "is already an action of the workflow"),
    ],
)
def test_the_load_refuses(route, message):
    assert message in _refusal(_workflow(route))


def test_the_load_refuses_a_route_with_no_default():
    data = _workflow()
    del data["actions"][1]["default"]

    assert "'default:' is required" in _refusal(data)


def test_the_load_refuses_an_entry_with_a_guard_of_its_own():
    data = _workflow()
    data["actions"][2]["guard"] = {"condition": "x", "on_false": "filter"}

    assert "'on_a', which starts the branch of case 'a', has a guard of its own" in _refusal(data)


def test_the_load_refuses_an_action_that_reads_two_cases_short_of_a_join():
    data = _workflow(actions=[_action("mixed", dependencies=["after_a", "on_b"])])

    assert "'mixed' reads the branch of case" in _refusal(data)


def test_a_read_of_another_case_through_the_context_scope_alone_is_refused_too():
    data = _workflow(
        actions=[_action("peek", dependencies=["on_b"], context_scope={"observe": ["after_a.x"]})]
    )

    assert "'peek' reads the branch of case" in _refusal(data)


def test_an_action_below_the_join_reads_every_case():
    data = _workflow(actions=[_action("publish", dependencies=["joined"])])

    assert "publish" in _by_name(expand_routes(data, WF))


@pytest.mark.parametrize(
    ("join", "message"),
    [
        ({"join": "joined", "of": []}, "'of:' must list"),
        ({"join": "joined", "of": ["nowhere"]}, "names 'nowhere'"),
        ({"join": "joined", "of": ["on_a"], "by": "x"}, "unknown key by"),
    ],
)
def test_the_load_refuses_a_join(join, message):
    assert message in _refusal(_workflow(join=join))


def _with_enum(data, enum):
    expanded = expand_routes(data, WF)
    _by_name(expanded)["classify"]["schema"] = {
        "name": "c",
        "fields": [{"id": "format", "type": "string", "enum": enum}],
    }
    return expanded


def test_7_3_a_case_value_outside_the_fields_enum_is_refused():
    data = _with_enum(_workflow({"cases": {"a": ["on_a"], "bb": ["on_b"]}}), ["a", "b"])

    with pytest.raises(ConfigurationError, match="case 'bb' is not a value of classify.format"):
        finish_routes(data, WF)


def test_an_enum_value_with_no_case_is_refused_under_default_filter():
    data = _with_enum(_workflow(), ["a", "b", "c"])

    with pytest.raises(ConfigurationError, match="c is a value of classify.format with no case"):
        finish_routes(data, WF)


def test_an_enum_value_with_no_case_enters_a_default_branch():
    data = _with_enum(
        _workflow({"default": ["on_other"]}, actions=[_action("on_other")]), ["a", "b", "c"]
    )

    finish_routes(copy.deepcopy(data), WF)


def test_a_field_with_no_enum_is_not_checked():
    data = expand_routes(_workflow(), WF)

    finish_routes(data, WF)


@pytest.mark.parametrize(
    "declared",
    [
        {"id": "format", "type": "integer", "enum": [1, 2]},
        {"id": "format", "type": "string", "enum": ["a", 2]},
        {"id": "format", "type": "integer"},
    ],
    ids=["integer-enum", "mixed-enum", "integer-type"],
)
def test_a_router_on_a_field_that_holds_no_strings_is_refused_at_load(declared):
    data = expand_routes(_workflow({"cases": {"1": ["on_a"], "2": ["on_b"]}}), WF)
    _by_name(data)["classify"]["schema"] = {"name": "c", "fields": [declared]}

    with pytest.raises(ConfigurationError, match="A router matches string values only"):
        finish_routes(data, WF)


def test_a_case_that_is_not_a_string_names_the_string_rule_and_no_quoting():
    message = _refusal(_workflow({"cases": {1: ["on_a"]}}))

    assert "A router matches string values only" in message
    assert "quote" not in message


def test_a_join_can_join_a_join_and_a_route_can_read_a_join():
    data = _workflow(
        actions=[
            {"join": "inner", "of": ["after_a", "on_b"]},
            {"route": "again", True: "inner.x", "cases": {"x": ["on_x"]}, "default": "filter"},
            _action("on_x"),
            {"join": "outer", "of": ["inner", "on_x"]},
        ],
        join=False,
    )

    actions = _by_name(expand_routes(data, WF))

    assert actions["again"]["dependencies"] == ["inner"]
    assert actions["outer"]["_builtin"]["of"] == ["inner", "on_x"]


def test_a_join_of_a_versioned_action_is_refused():
    data = _workflow(
        actions=[_action("voted", dependencies=["on_b"], versions={"range": [1, 2]})],
        join={"join": "joined", "of": ["after_a", "voted"]},
    )

    assert "names 'voted', which runs as versions" in _refusal(data)
    assert "Join the action that merges the versions of 'voted'" in _refusal(data)


def test_a_join_that_leaves_out_a_branch_of_a_router_is_warned_about(caplog):
    with caplog.at_level("WARNING"):
        expand_routes(_workflow(join={"join": "joined", "of": ["after_a"]}), WF)

    assert "takes the branches of router 'router' for a but not for b" in caplog.text


def test_a_join_of_every_branch_is_not_warned_about(caplog):
    with caplog.at_level("WARNING"):
        expand_routes(_workflow(), WF)

    assert "takes the branches" not in caplog.text


def test_a_route_or_a_join_in_a_branch_file_is_refused_in_one_sentence():
    from agent_actions.config.includes import parse_branch

    branch = {
        "branch": "pair",
        "description": "d",
        "actions": [{"route": "r", "on": "x.y", "cases": {"a": ["b"]}, "default": "filter"}],
    }

    with pytest.raises(ConfigurationError) as caught:
        parse_branch("pair", branch, WF)

    assert str(caught.value) == (
        f"Branch 'pair' (branches/pair.yml), included in {WF}: the branch contains a "
        "'- route:' or '- join:' entry. Write routes and joins in the workflow, not in a "
        "branch file."
    )

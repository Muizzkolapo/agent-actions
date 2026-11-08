"""The filter fan-in warning reads input paths through version bases and several hops."""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)

FILTER = {"condition": "approved == true", "on_false": "filter"}


def _action(name, *, dependencies=None, observe=None, guard=None):
    action = {
        "name": name,
        "prompt": f"Process {name}",
        "schema": {"type": "object", "properties": {"seen": {"type": "string"}}},
    }
    if dependencies:
        action["dependencies"] = dependencies
    if observe:
        action["context_scope"] = {"observe": observe}
    if guard:
        action["guard"] = guard
    return action


def _bypass_warnings(*actions):
    result = WorkflowStaticAnalyzer({"actions": list(actions)}).analyze()
    return [w.message for w in result.warnings if "via alternate dependency" in w.message]


def _versions(base, *, dependencies, observe):
    return [
        {**_action(f"{base}_{n}", dependencies=dependencies, observe=observe)}
        | {"version_base_name": base}
        for n in (1, 2)
    ]


def test_a_version_base_below_the_filter_is_not_a_bypass():
    assert (
        _bypass_warnings(
            _action("tag"),
            _action("check", dependencies=["tag"], observe=["tag.seen"], guard=FILTER),
            *_versions("vote", dependencies=["check"], observe=["check.seen"]),
            _action(
                "final",
                dependencies=["check", "vote"],
                observe=["check.seen", "vote_1.seen", "vote_2.seen"],
            ),
        )
        == []
    )


def test_a_version_base_beside_the_filter_is_a_bypass_named_by_its_versions():
    assert _bypass_warnings(
        _action("tag"),
        _action("check", dependencies=["tag"], observe=["tag.seen"], guard=FILTER),
        *_versions("vote", dependencies=["tag"], observe=["tag.seen"]),
        _action(
            "final",
            dependencies=["check", "vote"],
            observe=["check.seen", "vote_1.seen", "vote_2.seen"],
        ),
    ) == [
        "Action 'final' observes 'check.seen' but 'check' has guard with on_false: "
        "\"filter\". Records may arrive at 'final' via alternate dependency "
        "'vote_1, vote_2' with 'check' namespace as null."
    ]


def test_an_input_two_hops_below_the_filter_is_not_a_bypass():
    assert (
        _bypass_warnings(
            _action("tag"),
            _action("check", dependencies=["tag"], observe=["tag.seen"], guard=FILTER),
            _action("mid", dependencies=["check"], observe=["check.seen"]),
            _action("low", dependencies=["mid"], observe=["mid.seen"]),
            _action("final", dependencies=["check", "low"], observe=["check.seen", "low.seen"]),
        )
        == []
    )


def test_an_input_two_hops_beside_the_filter_is_a_bypass():
    (message,) = _bypass_warnings(
        _action("tag"),
        _action("check", dependencies=["tag"], observe=["tag.seen"], guard=FILTER),
        _action("mid", dependencies=["tag"], observe=["tag.seen"]),
        _action("low", dependencies=["mid"], observe=["mid.seen"]),
        _action("final", dependencies=["check", "low"], observe=["check.seen", "low.seen"]),
    )
    assert "via alternate dependency 'low' with 'check' namespace as null." in message

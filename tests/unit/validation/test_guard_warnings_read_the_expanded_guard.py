"""The guard warnings read an expanded guard's `clause` and `behavior` (1526).

Pre-flight analyzes the expanded config, where `guard: {condition, on_false}` has become
`{clause, behavior}`. The literal-type check read `condition` and never fired; the nullable
check read `condition` and `on_false`, so it printed the guard dict as its condition and
called every guard a filter; the skip and fan-in checks read `on_false` and so took every
guard for a filter.
"""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
    guard_clause_and_behavior,
)


def _expanded(clause, behavior):
    return {"clause": clause, "scope": "item", "behavior": behavior, "passthrough_on_error": True}


def _llm(name, fields, *, guard=None, dependencies=None, observe=None, types=None):
    action = {
        "name": name,
        "prompt": f"Process {name}",
        "schema": {
            "type": "object",
            "properties": {f: {"type": (types or {}).get(f, "string")} for f in fields},
        },
    }
    if guard:
        action["guard"] = guard
    if dependencies:
        action["dependencies"] = dependencies
    if observe:
        action["context_scope"] = {"observe": observe}
    return action


def _tool(name, fields, *, dependencies, observe):
    return {
        "name": name,
        "kind": "tool",
        "impl": f"{name}_impl",
        "dependencies": dependencies,
        "schema": [{"id": f, "type": t} for f, t in fields.items()],
        "context_scope": {"observe": observe},
    }


def _warnings(*actions, containing):
    result = WorkflowStaticAnalyzer({"actions": list(actions)}).analyze()
    return [w.message for w in result.warnings if containing in w.message]


def test_a_literal_the_field_type_never_matches_is_warned_about():
    messages = _warnings(
        _llm("review", ["approved"]),
        _llm(
            "publish",
            ["summary"],
            dependencies=["review"],
            observe=["review.approved"],
            guard=_expanded("review.approved == true", "filter"),
        ),
        containing="type mismatch",
    )

    assert len(messages) == 1, messages
    assert "'review.approved' is declared 'string'" in messages[0]


def test_the_nullable_warning_names_the_clause_and_behavior():
    messages = _warnings(
        _llm("extract", ["insights"], guard=_expanded("source.score >= 6", "skip")),
        _tool(
            "format_output",
            {"insights": "object"},
            dependencies=["extract"],
            observe=["extract.insights"],
        ),
        containing="may be None",
    )

    assert len(messages) == 1, messages
    assert "(guard: source.score >= 6, on_false: skip)" in messages[0], messages


def test_a_warn_guard_leaves_its_fields_set_so_no_nullable_warning():
    messages = _warnings(
        _llm("extract", ["insights"], guard=_expanded("source.score >= 6", "warn")),
        _tool(
            "format_output",
            {"insights": "object"},
            dependencies=["extract"],
            observe=["extract.insights"],
        ),
        containing="may be None",
    )

    assert messages == []


def test_an_observe_of_a_skip_guarded_field_is_warned_about():
    messages = _warnings(
        _llm("extract", ["insights"], guard=_expanded("source.score >= 6", "skip")),
        _llm("use", ["summary"], dependencies=["extract"], observe=["extract.insights"]),
        containing='on_false: "skip"',
    )

    assert len(messages) == 1, messages


def test_a_skip_guard_is_not_reported_as_a_filter_at_a_fan_in():
    actions = [
        _llm("a", ["x"], guard=_expanded("source.score >= 6", "skip")),
        _llm("b", ["y"]),
        _llm("join", ["z"], dependencies=["a", "b"], observe=["a.x", "b.y"]),
    ]

    assert _warnings(*actions, containing='on_false: "filter"') == []

    actions[0]["guard"] = _expanded("source.score >= 6", "filter")
    assert len(_warnings(*actions, containing='on_false: "filter"')) == 1


def test_guard_clause_and_behavior_reads_both_shapes():
    assert guard_clause_and_behavior(_expanded("a.b == 1", "skip")) == ("a.b == 1", "skip")
    assert guard_clause_and_behavior({"clause": "a.b == 1", "scope": "item"}) == (
        "a.b == 1",
        "filter",
    )
    assert guard_clause_and_behavior({"condition": "a.b == 1", "on_false": "warn"}) == (
        "a.b == 1",
        "warn",
    )
    assert guard_clause_and_behavior({"condition": "udf:check"}) == ("udf:check", "skip")
    assert guard_clause_and_behavior("a.b == 1") == ("a.b == 1", "filter")
    assert guard_clause_and_behavior({"scope": "item"}) is None
    assert guard_clause_and_behavior(None) is None

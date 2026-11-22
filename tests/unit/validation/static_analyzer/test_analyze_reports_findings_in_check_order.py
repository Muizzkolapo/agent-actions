"""`analyze()` reports every check's findings in one fixed order.

One workflow trips every check but the cycle check at once; the ordered (kind, action,
field) list pins the order in which `analyze()` runs them and assembles the result. A
cycle stops the type checker's other findings, so a second workflow pins the cycle error
against the type checker's own report of it, the template errors and the expansion errors.

Errors and warnings are kept in separate lists, so the relative order of a check that only
errs and one that only warns is not observable.
"""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _llm(name, fields, **extra):
    action = {
        "name": name,
        "prompt": f"Process {name}",
        "schema": {
            "type": "object",
            "properties": {f: {"type": "string"} for f in fields},
        },
        "context_scope": {"observe": ["source.*"]},
    }
    action.update(extra)
    return action


def _tool(name, fields, *, dependencies, observe):
    action = {
        "name": name,
        "kind": "tool",
        "impl": f"{name}_impl",
        "granularity": "file",
        "schema": [{"id": f, "type": "string"} for f in fields],
        "context_scope": {"observe": observe},
    }
    if dependencies:
        action["dependencies"] = dependencies
    return action


def _workflow():
    return {
        "name": "pinned",
        "actions": [
            _llm("prompt", ["x"]),
            {"name": "no_scope", "prompt": "Hi", "schema": {"type": "object", "properties": {}}},
            _llm(
                "review",
                ["approved", "score"],
                guard={"condition": "source.score >= 6", "on_false": "filter"},
            ),
            _llm(
                "skipper",
                ["insights"],
                guard={"condition": "source.flag == 1", "on_false": "skip"},
            ),
            _llm("other", ["y"]),
            _llm(
                "consumer",
                ["summary"],
                prompt="Use {{ stray.thing }} and {{ seed.rules }}",
                dependencies=["review", "skipper", "other", "relay"],
                guard={"condition": "review.approved == true", "on_false": "filter"},
                context_scope={
                    "observe": [
                        "review.approved",
                        "skipper.insights",
                        "other.y",
                        "seed.rules",
                        "seed_data.rules",
                        "ghost.*",
                        "relay.hop",
                        "origin.deep",
                    ],
                    "drop": ["review.missing", "detached.x"],
                },
            ),
            _llm("detached", ["x"]),
            _llm("free_text", ["a"], json_mode=False, dependencies=["other"]),
            _llm(
                "cached",
                ["a"],
                prompt="Read {{ source.text }}",
                model_vendor="anthropic",
                enable_prompt_caching=True,
            ),
            _llm(
                "cache_points",
                ["a"],
                prompt="Shared {% cache_point %} {{ source.text }}",
                model_vendor="openai",
            ),
            _tool("first_file", [], dependencies=None, observe=["source.*"]),
            _llm("scores", ["score"]),
            _tool(
                "merge_file",
                ["merged"],
                dependencies=["review", "scores"],
                observe=["review.score", "scores.score"],
            ),
            # 'consumer' falls back to its declared dependencies ('ghost' fails inference),
            # so 'origin' is reachable only through 'relay', which passes nothing through.
            _llm("origin", ["deep"]),
            _llm(
                "relay",
                ["hop"],
                dependencies=["origin"],
                context_scope={"observe": ["origin.deep"]},
            ),
            {
                "name": "unloadable",
                "prompt": "Hi",
                "schema_name": "no_such_schema",
                "context_scope": {"observe": ["source.*"]},
            },
            _llm("broken", ["a"], prompt="Read {{ source.text "),
            _llm(
                "looped",
                ["a"],
                prompt="{% for i in [1, 2] %}Shared {% cache_point %}{% endfor %}",
                model_vendor="anthropic",
                enable_prompt_caching=True,
            ),
        ],
    }


def _cyclic_workflow():
    return {
        "name": "cyclic",
        "actions": [
            _llm("ping", ["a"], context_scope={"observe": ["pong.b"]}),
            _llm("pong", ["b"], context_scope={"observe": ["ping.a"]}),
            _llm("broken", ["c"], prompt="Read {{ source.text "),
            _llm("wild", ["d"], context_scope={"observe": ["ghost.*"]}),
        ],
    }


def _assert_found(result, expected):
    issues = [*result.errors, *result.warnings]
    found = [(type(i).__name__, i.location.agent_name, i.location.config_field) for i in issues]
    assert found == [row[:3] for row in expected]
    for issue, (*_, fragment) in zip(issues, expected, strict=True):
        assert fragment in issue.message, (fragment, issue.message)


def test_findings_come_out_in_check_order():
    _assert_found(WorkflowStaticAnalyzer(_workflow()).analyze(), EXPECTED)


def test_a_cycle_comes_out_after_the_type_checker_and_before_template_errors():
    _assert_found(WorkflowStaticAnalyzer(_cyclic_workflow()).analyze(), EXPECTED_CYCLIC)


EXPECTED = [
    ("StaticTypeError", "consumer", "prompt", "Referenced action 'stray'"),
    ("StaticTypeError", "consumer", "context_scope.observe", "Referenced action 'seed_data'"),
    ("StaticTypeError", "consumer", "context_scope.observe", "Referenced action 'ghost'"),
    ("StaticTypeError", "consumer", "context_scope.drop", "Field 'missing' not found"),
    ("StaticTypeError", "consumer", "context_scope.drop", "'detached' is not reachable"),
    ("StaticTypeError", "broken", "prompt", "Template syntax error"),
    ("StaticTypeError", "consumer", "context_scope.observe", "Wildcard reference 'ghost.*'"),
    ("StaticTypeError", "prompt", "name", "is reserved"),
    ("StaticTypeError", "first_file", "dependencies", "reads at FILE granularity"),
    ("StaticTypeError", "unloadable", "schema", "cannot be loaded"),
    ("StaticTypeError", "no_scope", "context_scope", "has no context_scope"),
    ("StaticTypeError", "consumer", "context_scope", "template references namespace 'stray'"),
    ("StaticTypeError", "consumer", "context_scope.observe", "use 'seed.rules' instead"),
    ("StaticTypeError", "no_scope", "schema", "empty 'properties'"),
    ("StaticTypeError", "consumer", "context_scope.drop", "references non-existent field"),
    ("StaticTypeError", "looped", "prompt", "a cache point sits inside a loop"),
    ("StaticTypeWarning", "consumer", "context_scope.observe", "seed field 'rules'"),
    ("StaticTypeWarning", "consumer", "context_scope.drop", "not in its dependency chain"),
    ("StaticTypeWarning", "consumer", "guard", "type mismatch"),
    ("StaticTypeWarning", "consumer", "context_scope.observe", 'on_false: "skip"'),
    ("StaticTypeWarning", "consumer", "context_scope.observe", 'on_false: "filter"'),
    ("StaticTypeWarning", "merge_file", "context_scope.observe", 'on_false: "filter"'),
    ("StaticTypeWarning", "merge_file", "context_scope.observe", "colliding field names"),
    ("StaticTypeWarning", "free_text", "dependencies", "never referenced"),
    ("StaticTypeWarning", "consumer", "context_scope.observe", "non-direct dependency 'origin'"),
    ("StaticTypeWarning", "free_text", "json_mode", "json_mode=false"),
    ("StaticTypeWarning", "cached", "enable_prompt_caching", "reads record data"),
    ("StaticTypeWarning", "cache_points", "prompt", "holds a cache point"),
]

EXPECTED_CYCLIC = [
    ("StaticTypeError", "workflow", "dependencies", "Circular dependency"),
    ("StaticTypeError", "cyclic", "dependencies", "Circular dependency"),
    ("StaticTypeError", "broken", "prompt", "Template syntax error"),
    ("StaticTypeError", "wild", "context_scope.observe", "Wildcard reference 'ghost.*'"),
]

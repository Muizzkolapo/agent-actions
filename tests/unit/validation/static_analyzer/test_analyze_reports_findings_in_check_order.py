"""`analyze()` reports every check's findings in one fixed order.

One workflow trips most checks at once; the ordered (kind, action, field) list pins the
order in which `analyze()` runs them and assembles the result.
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
                dependencies=["review", "skipper", "other"],
                guard={"condition": "review.approved == true", "on_false": "filter"},
                context_scope={
                    "observe": [
                        "review.approved",
                        "skipper.insights",
                        "other.y",
                        "seed.rules",
                        "seed_data.rules",
                        "ghost.*",
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
        ],
    }


def test_findings_come_out_in_check_order():
    result = WorkflowStaticAnalyzer(_workflow()).analyze()

    issues = [*result.errors, *result.warnings]
    found = [(type(i).__name__, i.location.agent_name, i.location.config_field) for i in issues]
    assert found == [expected[:3] for expected in EXPECTED]
    for issue, (*_, fragment) in zip(issues, EXPECTED, strict=True):
        assert fragment in issue.message, (fragment, issue.message)


EXPECTED = [
    ("StaticTypeError", "consumer", "prompt", "Referenced action 'stray'"),
    ("StaticTypeError", "consumer", "context_scope.observe", "Referenced action 'seed_data'"),
    ("StaticTypeError", "consumer", "context_scope.observe", "Referenced action 'ghost'"),
    ("StaticTypeError", "consumer", "context_scope.drop", "Field 'missing' not found"),
    ("StaticTypeError", "consumer", "context_scope.drop", "'detached' is not reachable"),
    ("StaticTypeError", "consumer", "context_scope.observe", "Wildcard reference 'ghost.*'"),
    ("StaticTypeError", "prompt", "name", "is reserved"),
    ("StaticTypeError", "first_file", "dependencies", "reads at FILE granularity"),
    ("StaticTypeError", "no_scope", "context_scope", "has no context_scope"),
    ("StaticTypeError", "consumer", "context_scope", "template references namespace 'stray'"),
    ("StaticTypeError", "consumer", "context_scope.observe", "use 'seed.rules' instead"),
    ("StaticTypeError", "no_scope", "schema", "empty 'properties'"),
    ("StaticTypeError", "consumer", "context_scope.drop", "references non-existent field"),
    ("StaticTypeWarning", "consumer", "context_scope.observe", "seed field 'rules'"),
    ("StaticTypeWarning", "consumer", "context_scope.drop", "not in its dependency chain"),
    ("StaticTypeWarning", "consumer", "guard", "type mismatch"),
    ("StaticTypeWarning", "consumer", "context_scope.observe", 'on_false: "skip"'),
    ("StaticTypeWarning", "consumer", "context_scope.observe", 'on_false: "filter"'),
    ("StaticTypeWarning", "merge_file", "context_scope.observe", 'on_false: "filter"'),
    ("StaticTypeWarning", "merge_file", "context_scope.observe", "colliding field names"),
    ("StaticTypeWarning", "free_text", "dependencies", "never referenced"),
    ("StaticTypeWarning", "free_text", "json_mode", "json_mode=false"),
    ("StaticTypeWarning", "cached", "enable_prompt_caching", "reads record data"),
    ("StaticTypeWarning", "cache_points", "prompt", "holds a cache point"),
]

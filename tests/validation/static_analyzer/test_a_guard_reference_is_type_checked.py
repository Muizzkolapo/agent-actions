"""The static analyzer checks a guard clause's `namespace.field` reads (1516)."""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _errors(guard_clause: str, **upstream) -> list[str]:
    config = {
        "name": "wf",
        "actions": [
            {
                "name": "up",
                "kind": "tool",
                "impl": "fix1516_up",
                "schema": {"type": "object", "properties": {"score": {"type": "number"}}},
                "context_scope": {"observe": ["source.x"]},
                **upstream,
            },
            {
                "name": "side",
                "prompt": "p",
                "schema": {"type": "object", "properties": {"n": {"type": "number"}}},
                "context_scope": {"observe": ["source.x"]},
            },
            {
                "name": "down",
                "prompt": "{{ up.score }}",
                "dependencies": ["up"],
                "schema": {"type": "object", "properties": {"out": {"type": "string"}}},
                "context_scope": {"observe": ["up.score"]},
                "guard": {"clause": guard_clause, "scope": "item"},
            },
        ],
    }
    result = WorkflowStaticAnalyzer(config).analyze()
    return [e.message for e in result.errors if e.location.config_field == "guard"]


def test_an_unknown_action_and_an_unknown_field_are_errors():
    assert _errors("nosuch.score > 1") == [
        "Referenced action 'nosuch' does not exist in workflow"
    ]
    assert _errors("up.scor > 1") == ["Field 'scor' not found in action 'up' output schema"]


def test_a_real_field_is_not_an_error():
    assert _errors("up.score > 1 and source.x == 'a'") == []


def test_reach_and_self_reads_are_left_to_the_upstream_check():
    """`find_reads_not_upstream` refuses these in words about the guard."""
    assert _errors("side.n > 1") == []
    assert _errors("down.out == 'x'") == []


def test_a_name_a_dependency_promotes_is_not_an_action():
    assert _errors("verdict.level == 'x'", output_field="verdict") == []


def test_any_name_may_be_a_field_a_version_merge_tool_spread_flat():
    spread = {"granularity": "file", "version_consumption": {"source": "v", "pattern": "merge"}}

    assert _errors("decision.level == 'x'", **spread) == []


def test_a_field_the_upstream_observes_or_passes_through_is_not_its_own():
    forwarding = {"context_scope": {"observe": ["source.x"], "passthrough": ["source.y"]}}

    assert _errors("up.x == 'a'", **forwarding) == [
        "Field 'x' not found in action 'up' output schema"
    ]
    assert _errors("up.y == 'a'", **forwarding) == [
        "Field 'y' not found in action 'up' output schema"
    ]


def test_the_verdict_expectations_attach_is_on_the_namespace():
    assert _errors("up.expect.overall_pass == true") == []


def test_a_field_an_open_schema_admits_is_not_an_error():
    open_schema = {
        "schema": {
            "type": "object",
            "properties": {"score": {"type": "number"}},
            "additionalProperties": True,
        }
    }

    assert _errors("up.unlisted == 'x'", **open_schema) == []

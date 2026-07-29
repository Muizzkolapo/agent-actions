"""Preflight flags FILE-mode tools whose observe list collides across namespaces."""

from agent_actions.validation.static_analyzer import analyze_workflow

MARKER = "colliding field names"


def _collision_warnings(result):
    return [w for w in result.warnings if MARKER in w.message]


def test_file_tool_two_wildcard_observe_flags_collision():
    workflow_config = {
        "actions": [
            {"name": "tag_concept", "kind": "tool"},
            {"name": "dedup", "kind": "tool"},
            {
                "name": "dedup_by_concept",
                "kind": "tool",
                "granularity": "file",
                "depends_on": ["tag_concept", "dedup"],
                "context_scope": {"observe": ["tag_concept.*", "dedup.*"]},
            },
        ]
    }

    warnings = _collision_warnings(analyze_workflow(workflow_config))

    assert len(warnings) == 1
    msg = warnings[0].message
    assert "dedup_by_concept" in msg
    # Two wildcard namespaces both qualify; the message names both.
    assert "tag_concept.*" in msg
    assert "dedup.*" in msg


def test_file_tool_specific_field_collision_flags_the_shared_key():
    workflow_config = {
        "actions": [
            {
                "name": "action_a",
                "schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
            },
            {
                "name": "action_b",
                "schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
            },
            {
                "name": "merge_tool",
                "kind": "tool",
                "granularity": "file",
                "depends_on": ["action_a", "action_b"],
                "context_scope": {"observe": ["action_a.answer", "action_b.answer"]},
            },
        ]
    }

    warnings = _collision_warnings(analyze_workflow(workflow_config))

    assert len(warnings) == 1
    msg = warnings[0].message
    assert "merge_tool" in msg
    assert "action_a.answer" in msg
    assert "action_b.answer" in msg


def test_file_tool_distinct_fields_no_warning():
    workflow_config = {
        "actions": [
            {
                "name": "action_a",
                "schema": {"type": "object", "properties": {"foo": {"type": "string"}}},
            },
            {
                "name": "action_b",
                "schema": {"type": "object", "properties": {"bar": {"type": "string"}}},
            },
            {
                "name": "merge_tool",
                "kind": "tool",
                "granularity": "file",
                "depends_on": ["action_a", "action_b"],
                "context_scope": {"observe": ["action_a.foo", "action_b.bar"]},
            },
        ]
    }

    assert _collision_warnings(analyze_workflow(workflow_config)) == []


def test_record_mode_tool_collision_not_flagged():
    # Record-granularity tools receive namespaced context, not flat keys — no collision.
    workflow_config = {
        "actions": [
            {"name": "tag_concept", "kind": "tool"},
            {"name": "dedup", "kind": "tool"},
            {
                "name": "dedup_by_concept",
                "kind": "tool",
                "granularity": "record",
                "depends_on": ["tag_concept", "dedup"],
                "context_scope": {"observe": ["tag_concept.*", "dedup.*"]},
            },
        ]
    }

    assert _collision_warnings(analyze_workflow(workflow_config)) == []


def test_llm_action_collision_not_flagged():
    # Non-tool actions get namespaced Jinja context; the flat-key hazard is tool-only.
    workflow_config = {
        "actions": [
            {"name": "tag_concept", "kind": "tool"},
            {"name": "dedup", "kind": "tool"},
            {
                "name": "writer",
                "granularity": "file",
                "depends_on": ["tag_concept", "dedup"],
                "prompt": "write",
                "context_scope": {"observe": ["tag_concept.*", "dedup.*"]},
            },
        ]
    }

    assert _collision_warnings(analyze_workflow(workflow_config)) == []

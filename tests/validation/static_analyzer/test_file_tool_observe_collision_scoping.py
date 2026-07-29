"""Scoping edges for the FILE-tool observe-collision preflight check."""

from agent_actions.validation.static_analyzer import analyze_workflow

MARKER = "colliding field names"


def _collision_warnings(result):
    return [w for w in result.warnings if MARKER in w.message]


def test_tool_declared_via_model_vendor_is_flagged():
    # Tools can be declared with model_vendor: tool instead of kind: tool.
    workflow_config = {
        "actions": [
            {"name": "tag_concept", "kind": "tool"},
            {"name": "dedup", "kind": "tool"},
            {
                "name": "dedup_by_concept",
                "model_vendor": "tool",
                "granularity": "file",
                "depends_on": ["tag_concept", "dedup"],
                "context_scope": {"observe": ["tag_concept.*", "dedup.*"]},
            },
        ]
    }

    warnings = _collision_warnings(analyze_workflow(workflow_config))
    assert len(warnings) == 1
    assert "dedup_by_concept" in warnings[0].message


def test_file_tool_without_observe_no_warning():
    # context_scope present but no observe — the most common legit config.
    workflow_config = {
        "actions": [
            {"name": "producer", "kind": "tool"},
            {
                "name": "flatten",
                "kind": "tool",
                "granularity": "file",
                "depends_on": ["producer"],
                "context_scope": {"drop": ["producer.debug"]},
            },
        ]
    }

    assert _collision_warnings(analyze_workflow(workflow_config)) == []


def test_duplicate_wildcard_same_namespace_no_warning():
    # Same namespace observed twice does NOT qualify at runtime (qualify_wildcards
    # needs 2+ distinct namespaces), so preflight must not warn on it either.
    workflow_config = {
        "actions": [
            {"name": "producer", "kind": "tool"},
            {
                "name": "flatten",
                "kind": "tool",
                "granularity": "file",
                "depends_on": ["producer"],
                "context_scope": {"observe": ["producer.*", "producer.*"]},
            },
        ]
    }

    assert _collision_warnings(analyze_workflow(workflow_config)) == []

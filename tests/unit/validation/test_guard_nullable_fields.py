"""Tests for _check_guard_nullable_fields() pre-flight check.

Detects fields that may be None due to upstream guard filtering
and warns when a downstream tool action's schema declares those
fields as non-nullable types.
"""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _make_workflow(*actions):
    """Build a minimal workflow config from action dicts."""
    return {"actions": list(actions)}


def _llm_action(name, *, schema_fields=None, guard=None, depends_on=None, observe=None):
    """Build an LLM action config."""
    action = {"name": name, "prompt": f"Process {name}"}
    if schema_fields:
        action["schema"] = {
            "type": "object",
            "properties": {f: {"type": "string"} for f in schema_fields},
        }
    if guard:
        action["guard"] = guard
    if depends_on:
        action["depends_on"] = depends_on
    if observe:
        action["context_scope"] = {"observe": observe}
    return action


def _tool_action(name, *, schema_fields, depends_on=None, observe=None):
    """Build a tool action config with a list-style output schema."""
    action = {
        "name": name,
        "kind": "tool",
        "impl": f"{name}_impl",
        "depends_on": depends_on or [],
        "schema": [{"id": f, "type": t} for f, t in schema_fields.items()],
    }
    if observe:
        action["context_scope"] = {"observe": observe}
    return action


class TestGuardNullableFields:
    """Tests for guard-nullable field detection in pre-flight static analysis."""

    def test_guarded_action_to_tool_with_non_nullable_field_warns(self):
        """Basic case: guarded action -> tool with non-nullable field -> warns."""
        workflow = _make_workflow(
            _llm_action(
                "extract_insights",
                schema_fields=["insights"],
                guard={"condition": "score >= 6", "on_false": "filter"},
            ),
            _tool_action(
                "format_output",
                schema_fields={"insights": "object", "summary": "string"},
                depends_on=["extract_insights"],
                observe=["extract_insights.insights"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 1
        assert "insights" in guard_warnings[0].message
        assert "extract_insights" in guard_warnings[0].message
        assert "format_output" in guard_warnings[0].message

    def test_no_guard_produces_no_warning(self):
        """Same setup but no guard on upstream -> no warning."""
        workflow = _make_workflow(
            _llm_action("extract_insights", schema_fields=["insights"]),
            _tool_action(
                "format_output",
                schema_fields={"insights": "object"},
                depends_on=["extract_insights"],
                observe=["extract_insights.insights"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 0

    def test_guard_with_non_filter_behavior_no_warning(self):
        """Guard with on_false: 'warn' does not produce None values -> no warning."""
        workflow = _make_workflow(
            _llm_action(
                "extract_insights",
                schema_fields=["insights"],
                guard={"condition": "score >= 6", "on_false": "warn"},
            ),
            _tool_action(
                "format_output",
                schema_fields={"insights": "object"},
                depends_on=["extract_insights"],
                observe=["extract_insights.insights"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 0

    def test_field_not_in_consumer_schema_no_warning(self):
        """Guarded field observed but not declared in consumer schema -> no warning."""
        workflow = _make_workflow(
            _llm_action(
                "extract_insights",
                schema_fields=["insights"],
                guard={"condition": "score >= 6", "on_false": "filter"},
            ),
            _tool_action(
                "format_output",
                schema_fields={"summary": "string"},  # insights NOT in schema
                depends_on=["extract_insights"],
                observe=["extract_insights.insights"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 0

    def test_multiple_guarded_upstreams_warn_independently(self):
        """Two guarded actions -> one tool -> warns for each independently."""
        workflow = _make_workflow(
            _llm_action(
                "action_a",
                schema_fields=["field_a"],
                guard={"condition": "x > 0", "on_false": "filter"},
            ),
            _llm_action(
                "action_b",
                schema_fields=["field_b"],
                guard={"condition": "y > 0", "on_false": "skip"},
            ),
            _tool_action(
                "consumer",
                schema_fields={"field_a": "object", "field_b": "array"},
                depends_on=["action_a", "action_b"],
                observe=["action_a.field_a", "action_b.field_b"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 2
        warned_fields = {w.referenced_field for w in guard_warnings}
        assert warned_fields == {"field_a", "field_b"}

    def test_non_tool_consumer_no_warning(self):
        """LLM action consuming guarded fields -> no warning (no schema enforcement)."""
        workflow = _make_workflow(
            _llm_action(
                "extract_insights",
                schema_fields=["insights"],
                guard={"condition": "score >= 6", "on_false": "filter"},
            ),
            _llm_action(
                "summarizer",
                schema_fields=["summary"],
                depends_on=["extract_insights"],
                observe=["extract_insights.insights"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 0

    def test_string_guard_defaults_to_filter(self):
        """String-style guard (legacy) defaults to filter behavior -> warns."""
        workflow = _make_workflow(
            _llm_action(
                "extract_insights",
                schema_fields=["insights"],
                guard="score >= 6",
            ),
            _tool_action(
                "format_output",
                schema_fields={"insights": "object"},
                depends_on=["extract_insights"],
                observe=["extract_insights.insights"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 1

    def test_transitive_passthrough_wildcard_warns(self):
        """A -> B (passthrough A.*) -> C (tool observes B.field) warns for A's guard."""
        workflow = _make_workflow(
            _llm_action(
                "guarded_action",
                schema_fields=["insights"],
                guard={"condition": "score >= 6", "on_false": "filter"},
            ),
            _llm_action(
                "intermediate",
                schema_fields=["extra"],
                depends_on=["guarded_action"],
                observe=["guarded_action.insights"],
            ),
            _tool_action(
                "final_tool",
                schema_fields={"insights": "object"},
                depends_on=["intermediate"],
                observe=["intermediate.insights"],
            ),
        )
        # intermediate needs to passthrough guarded_action's fields
        workflow["actions"][1]["context_scope"]["passthrough"] = ["guarded_action.*"]

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 1
        assert "insights" in guard_warnings[0].message
        # The warning should trace back to the guarded action, not the intermediate
        assert guard_warnings[0].referenced_agent == "guarded_action"

    def test_transitive_specific_passthrough_warns(self):
        """Specific passthrough (not wildcard) also detected transitively."""
        workflow = _make_workflow(
            _llm_action(
                "guarded_action",
                schema_fields=["data"],
                guard={"condition": "valid == true", "on_false": "skip"},
            ),
            _llm_action(
                "middle",
                schema_fields=["other"],
                depends_on=["guarded_action"],
                observe=["guarded_action.data"],
            ),
            _tool_action(
                "consumer",
                schema_fields={"data": "object"},
                depends_on=["middle"],
                observe=["middle.data"],
            ),
        )
        workflow["actions"][1]["context_scope"]["passthrough"] = ["guarded_action.data"]

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 1
        assert guard_warnings[0].referenced_agent == "guarded_action"

    def test_nullable_type_suppresses_warning(self):
        """Schema field with nullable type (e.g. ["object", "null"]) does not warn."""
        workflow = _make_workflow(
            _llm_action(
                "guarded",
                schema_fields=["data"],
                guard={"condition": "ok == true", "on_false": "filter"},
            ),
            {
                "name": "tool",
                "kind": "tool",
                "impl": "tool_impl",
                "depends_on": ["guarded"],
                "context_scope": {"observe": ["guarded.data"]},
                "schema": [{"id": "data", "type": ["object", "null"]}],
            },
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 0

    def test_warning_includes_hint(self):
        """Warning message includes actionable hint."""
        workflow = _make_workflow(
            _llm_action(
                "guarded",
                schema_fields=["data"],
                guard={"condition": "ok == true", "on_false": "filter"},
            ),
            _tool_action(
                "tool",
                schema_fields={"data": "object"},
                depends_on=["guarded"],
                observe=["guarded.data"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        guard_warnings = [w for w in result.warnings if "may be None" in w.message]
        assert len(guard_warnings) == 1
        assert guard_warnings[0].hint is not None
        assert "remove" in guard_warnings[0].hint or "handle None" in guard_warnings[0].hint

"""Tests for guard-nullable field detection and auto-fix.

Part 1: _check_guard_nullable_fields() pre-flight warnings.
Part 2: apply_guard_nullable_schema_fixes() auto-fix of json_output_schema.
Part 3: Runtime validation with guard-nullable fields.
"""

import copy

import pytest

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
    _make_schema_field_nullable,
    apply_guard_nullable_schema_fixes,
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


# ── Part 2: Auto-fix tests ──────────────────────────────────────────


def _tool_config(name, *, json_output_schema, observe, guard=None):
    """Build a tool action config dict as it appears in action_configs at runtime."""
    config = {
        "model_vendor": "tool",
        "json_output_schema": json_output_schema,
        "context_scope": {"observe": observe},
    }
    if guard:
        config["guard"] = guard
    return name, config


def _guarded_llm_config(name, *, guard):
    """Build a guarded LLM action config dict."""
    return name, {"guard": guard, "model_vendor": "openai"}


class TestMakeSchemaFieldNullable:
    """Tests for _make_schema_field_nullable helper."""

    def test_string_type_becomes_list(self):
        schema = {"properties": {"field": {"type": "object"}}}
        assert _make_schema_field_nullable(schema, "field") is True
        assert schema["properties"]["field"]["type"] == ["object", "null"]

    def test_already_nullable_not_modified(self):
        schema = {"properties": {"field": {"type": ["object", "null"]}}}
        assert _make_schema_field_nullable(schema, "field") is False

    def test_list_type_without_null_gets_null_appended(self):
        schema = {"properties": {"field": {"type": ["string", "integer"]}}}
        assert _make_schema_field_nullable(schema, "field") is True
        assert schema["properties"]["field"]["type"] == ["string", "integer", "null"]

    def test_field_not_in_schema_returns_false(self):
        schema = {"properties": {"other": {"type": "object"}}}
        assert _make_schema_field_nullable(schema, "missing") is False

    def test_handles_array_items_format(self):
        schema = {
            "type": "array",
            "items": {"properties": {"field": {"type": "object"}}},
        }
        assert _make_schema_field_nullable(schema, "field") is True
        assert schema["items"]["properties"]["field"]["type"] == ["object", "null"]

    def test_handles_nested_schema_wrapper(self):
        schema = {"schema": {"properties": {"field": {"type": "string"}}}}
        assert _make_schema_field_nullable(schema, "field") is True
        assert schema["schema"]["properties"]["field"]["type"] == ["string", "null"]

    def test_null_type_not_modified(self):
        schema = {"properties": {"field": {"type": "null"}}}
        assert _make_schema_field_nullable(schema, "field") is False

    def test_no_type_key_returns_false(self):
        schema = {"properties": {"field": {"description": "no type"}}}
        assert _make_schema_field_nullable(schema, "field") is False

    def test_empty_schema_returns_false(self):
        assert _make_schema_field_nullable({}, "field") is False


class TestApplyGuardNullableSchemaFixes:
    """Tests for apply_guard_nullable_schema_fixes auto-fix function."""

    def test_basic_fix_makes_field_nullable(self):
        """Guarded upstream + tool observing -> field made nullable."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"insights": {"type": "object"}},
                        "required": ["insights"],
                    },
                    observe=["extract.insights"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)

        assert fixes == ["consumer.insights"]
        assert action_configs["consumer"]["json_output_schema"]["properties"]["insights"][
            "type"
        ] == ["object", "null"]

    def test_no_guard_no_fix(self):
        """No guarded upstream -> no fixes applied."""
        action_configs = dict(
            [
                ("extract", {"model_vendor": "openai"}),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"insights": {"type": "object"}},
                    },
                    observe=["extract.insights"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_non_tool_consumer_not_fixed(self):
        """LLM consumer is not fixed (no strict schema validation)."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                (
                    "consumer",
                    {
                        "model_vendor": "openai",
                        "json_output_schema": {
                            "type": "object",
                            "properties": {"insights": {"type": "object"}},
                        },
                        "context_scope": {"observe": ["extract.insights"]},
                    },
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_already_nullable_skipped(self):
        """Field already nullable -> not modified, not in fix list."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"insights": {"type": ["object", "null"]}},
                    },
                    observe=["extract.insights"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_wildcard_observe_not_fixed(self):
        """Wildcard observe (action.*) -> not fixed (can't enumerate fields)."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"insights": {"type": "object"}},
                    },
                    observe=["extract.*"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_multiple_guarded_sources_fixed(self):
        """Two guarded upstreams -> both fields fixed."""
        action_configs = dict(
            [
                _guarded_llm_config("action_a", guard={"condition": "x > 0", "on_false": "filter"}),
                _guarded_llm_config("action_b", guard={"condition": "y > 0", "on_false": "skip"}),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {
                            "field_a": {"type": "object"},
                            "field_b": {"type": "array"},
                        },
                    },
                    observe=["action_a.field_a", "action_b.field_b"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert sorted(fixes) == ["consumer.field_a", "consumer.field_b"]

    def test_string_guard_defaults_to_filter(self):
        """String-style guard -> defaults to filter -> fix applied."""
        action_configs = dict(
            [
                ("extract", {"model_vendor": "openai", "guard": "score >= 6"}),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"data": {"type": "object"}},
                    },
                    observe=["extract.data"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == ["consumer.data"]

    def test_guard_warn_behavior_not_fixed(self):
        """on_false: 'warn' does not produce None -> no fix."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "warn"},
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"data": {"type": "object"}},
                    },
                    observe=["extract.data"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_post_expansion_guard_format_warn_not_fixed(self):
        """Post-expansion guard uses 'behavior' key, not 'on_false'. Warn must not fix."""
        action_configs = dict(
            [
                (
                    "extract",
                    {
                        "model_vendor": "openai",
                        "guard": {"clause": "score >= 6", "scope": "item", "behavior": "warn"},
                    },
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"data": {"type": "object"}},
                    },
                    observe=["extract.data"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_post_expansion_guard_format_filter_fixed(self):
        """Post-expansion guard with behavior: filter -> field made nullable."""
        action_configs = dict(
            [
                (
                    "extract",
                    {
                        "model_vendor": "openai",
                        "guard": {"clause": "score >= 6", "scope": "item", "behavior": "filter"},
                    },
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"data": {"type": "object"}},
                    },
                    observe=["extract.data"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == ["consumer.data"]

    def test_field_not_in_json_output_schema_not_fixed(self):
        """Observed field not in consumer's json_output_schema -> no fix."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"other_field": {"type": "object"}},
                    },
                    observe=["extract.missing_field"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_no_json_output_schema_skipped(self):
        """Tool without json_output_schema -> skipped."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                (
                    "consumer",
                    {
                        "model_vendor": "tool",
                        "context_scope": {"observe": ["extract.data"]},
                    },
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_modifies_schema_in_place(self):
        """Verify the schema dict is modified in place (shared reference)."""
        schema = {
            "type": "object",
            "properties": {"insights": {"type": "object"}},
        }
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config("consumer", json_output_schema=schema, observe=["extract.insights"]),
            ]
        )

        apply_guard_nullable_schema_fixes(action_configs)

        # The original schema object should be modified
        assert schema["properties"]["insights"]["type"] == ["object", "null"]

    def test_transitive_wildcard_passthrough_fixed(self):
        """A -> B (passthrough A.*) -> C (tool observes B.field) -> field made nullable."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "guarded_action",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                (
                    "intermediate",
                    {
                        "model_vendor": "openai",
                        "context_scope": {
                            "observe": ["guarded_action.insights"],
                            "passthrough": ["guarded_action.*"],
                        },
                    },
                ),
                _tool_config(
                    "final_tool",
                    json_output_schema={
                        "type": "object",
                        "properties": {"insights": {"type": "object"}},
                    },
                    observe=["intermediate.insights"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)

        assert fixes == ["final_tool.insights"]
        assert action_configs["final_tool"]["json_output_schema"]["properties"]["insights"][
            "type"
        ] == ["object", "null"]

    def test_transitive_specific_passthrough_fixed(self):
        """Specific passthrough (not wildcard) also fixed transitively."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "guarded",
                    guard={"condition": "ok == true", "on_false": "skip"},
                ),
                (
                    "middle",
                    {
                        "model_vendor": "openai",
                        "context_scope": {
                            "observe": ["guarded.data"],
                            "passthrough": ["guarded.data"],
                        },
                    },
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"data": {"type": "object"}},
                    },
                    observe=["middle.data"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)

        assert fixes == ["consumer.data"]

    def test_transitive_non_matching_passthrough_not_fixed(self):
        """Passthrough from guarded action but different field -> not fixed."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "guarded",
                    guard={"condition": "ok == true", "on_false": "filter"},
                ),
                (
                    "middle",
                    {
                        "model_vendor": "openai",
                        "context_scope": {
                            "observe": ["guarded.other"],
                            "passthrough": ["guarded.other"],
                        },
                    },
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"data": {"type": "object"}},
                    },
                    observe=["middle.data"],
                ),
            ]
        )

        fixes = apply_guard_nullable_schema_fixes(action_configs)
        assert fixes == []

    def test_idempotent_second_call_returns_empty(self):
        """Calling fix twice returns empty on second call."""
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config(
                    "consumer",
                    json_output_schema={
                        "type": "object",
                        "properties": {"insights": {"type": "object"}},
                    },
                    observe=["extract.insights"],
                ),
            ]
        )

        first = apply_guard_nullable_schema_fixes(action_configs)
        second = apply_guard_nullable_schema_fixes(action_configs)

        assert first == ["consumer.insights"]
        assert second == []


# ── Part 3: Runtime validation integration ──────────────────────────


class TestGuardNullableRuntimeValidation:
    """Verify that auto-fixed schemas pass jsonschema validation correctly."""

    def test_null_value_passes_after_fix(self):
        """After fix, jsonschema.validate accepts None for guard-nullable field."""
        import jsonschema

        schema = {
            "type": "object",
            "properties": {
                "insights": {"type": "object"},
                "summary": {"type": "string"},
            },
            "required": ["insights", "summary"],
            "additionalProperties": False,
        }

        # Before fix: None fails
        data = {"insights": None, "summary": "test"}
        with pytest.raises(jsonschema.ValidationError, match="None is not of type 'object'"):
            jsonschema.validate(instance=data, schema=schema)

        # Apply fix
        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config("consumer", json_output_schema=schema, observe=["extract.insights"]),
            ]
        )
        apply_guard_nullable_schema_fixes(action_configs)

        # After fix: None passes
        jsonschema.validate(instance=data, schema=schema)

    def test_valid_object_still_passes_after_fix(self):
        """Non-null object values still pass validation after fix."""
        import jsonschema

        schema = {
            "type": "object",
            "properties": {"insights": {"type": "object"}},
            "required": ["insights"],
        }

        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config("consumer", json_output_schema=schema, observe=["extract.insights"]),
            ]
        )
        apply_guard_nullable_schema_fixes(action_configs)

        data = {"insights": {"key": "value"}}
        jsonschema.validate(instance=data, schema=schema)

    def test_wrong_type_still_fails_after_fix(self):
        """Non-null wrong type (e.g. string instead of object) still fails."""
        import jsonschema

        schema = {
            "type": "object",
            "properties": {"insights": {"type": "object"}},
            "required": ["insights"],
        }

        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config("consumer", json_output_schema=schema, observe=["extract.insights"]),
            ]
        )
        apply_guard_nullable_schema_fixes(action_configs)

        data = {"insights": "not an object"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=data, schema=schema)

    def test_missing_required_field_still_fails(self):
        """Required field completely absent still fails (not too permissive)."""
        import jsonschema

        schema = {
            "type": "object",
            "properties": {"insights": {"type": "object"}, "summary": {"type": "string"}},
            "required": ["insights", "summary"],
        }

        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config("consumer", json_output_schema=schema, observe=["extract.insights"]),
            ]
        )
        apply_guard_nullable_schema_fixes(action_configs)

        # "insights" is required — absent should still fail
        data = {"summary": "test"}
        with pytest.raises(jsonschema.ValidationError, match="'insights' is a required property"):
            jsonschema.validate(instance=data, schema=schema)

    def test_non_guarded_field_type_unchanged(self):
        """Fields NOT from guarded upstreams keep original strict type."""
        import jsonschema

        schema = {
            "type": "object",
            "properties": {
                "insights": {"type": "object"},
                "summary": {"type": "string"},
            },
            "required": ["insights", "summary"],
        }
        original_schema = copy.deepcopy(schema)

        action_configs = dict(
            [
                _guarded_llm_config(
                    "extract",
                    guard={"condition": "score >= 6", "on_false": "filter"},
                ),
                _tool_config("consumer", json_output_schema=schema, observe=["extract.insights"]),
            ]
        )
        apply_guard_nullable_schema_fixes(action_configs)

        # "insights" was fixed, "summary" was NOT
        assert schema["properties"]["insights"]["type"] == ["object", "null"]
        assert (
            schema["properties"]["summary"]["type"]
            == original_schema["properties"]["summary"]["type"]
        )

        # None for "summary" should still fail
        data = {"insights": {"key": "val"}, "summary": None}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=data, schema=schema)

"""Tests for guard-nullable field detection and auto-fix.

Part 1: what pre-flight warns about a guarded field a tool observes.
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


def _llm_action(name, *, schema_fields=None, guard=None, dependencies=None, observe=None):
    """Build an LLM action config."""
    action = {"name": name, "prompt": f"Process {name}"}
    if schema_fields:
        action["schema"] = {
            "type": "object",
            "properties": {f: {"type": "string"} for f in schema_fields},
        }
    if guard:
        action["guard"] = guard
    if dependencies:
        action["dependencies"] = dependencies
    if observe:
        action["context_scope"] = {"observe": observe}
    return action


def _tool_action(name, *, schema_fields, dependencies=None, observe=None):
    """Build a tool action config with a list-style output schema."""
    action = {
        "name": name,
        "kind": "tool",
        "impl": f"{name}_impl",
        "dependencies": dependencies or [],
        "schema": [{"id": f, "type": t} for f, t in schema_fields.items()],
    }
    if observe:
        action["context_scope"] = {"observe": observe}
    return action


class TestAGuardedFieldAToolObserves:
    """A tool reading a guarded action's field (1536).

    A filter removes the record from every action below it, so the tool never reads the
    field as None; a skip leaves the namespace null, which the skip-observe warning reports
    for every action, tools included. `apply_guard_nullable_schema_fixes` makes the tool's
    schema accept the null, so a separate warning that the schema rejects it was wrong.
    """

    @staticmethod
    def _warnings(behavior):
        workflow = _make_workflow(
            _llm_action(
                "extract_insights",
                schema_fields=["insights"],
                guard={"condition": "source.score >= 6", "on_false": behavior},
            ),
            _tool_action(
                "format_output",
                schema_fields={"insights": "object"},
                dependencies=["extract_insights"],
                observe=["extract_insights.insights"],
            ),
        )
        result = WorkflowStaticAnalyzer(workflow).analyze()
        return [
            w.message
            for w in result.warnings
            if w.location.raw_reference == "extract_insights.insights"
            or "extract_insights" in w.message
        ]

    def test_a_filter_guard_is_not_warned_about(self):
        assert self._warnings("filter") == []

    def test_a_skip_guard_is_warned_about_once(self):
        messages = self._warnings("skip")

        assert len(messages) == 1, messages
        assert "may be null at runtime" in messages[0]

    def test_a_read_under_a_forwarding_action_is_refused(self):
        """A field passed through stays stored under the guarded action's namespace.

        `intermediate.insights` reads intermediate's own output, so pre-flight refuses it
        when intermediate's schema lacks it.
        """
        for passthrough in (["guarded_action.*"], ["guarded_action.insights"]):
            workflow = _make_workflow(
                _llm_action(
                    "guarded_action",
                    schema_fields=["insights"],
                    guard={"condition": "guarded_action.score >= 6", "on_false": "skip"},
                ),
                _llm_action(
                    "intermediate",
                    schema_fields=["extra"],
                    dependencies=["guarded_action"],
                    observe=["guarded_action.insights"],
                ),
                _tool_action(
                    "final_tool",
                    schema_fields={"insights": "object"},
                    dependencies=["intermediate"],
                    observe=["intermediate.insights"],
                ),
            )
            workflow["actions"][1]["context_scope"]["passthrough"] = passthrough

            result = WorkflowStaticAnalyzer(workflow).analyze()

            assert any(
                "'insights' not found in action 'intermediate'" in e.message for e in result.errors
            ), passthrough


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

    def test_a_read_under_a_forwarding_action_is_not_fixed(self):
        """A field passed through stays under the guarded action's namespace (1536)."""
        for passthrough in (["guarded.*"], ["guarded.data"]):
            action_configs = dict(
                [
                    (
                        "guarded",
                        {
                            "model_vendor": "openai",
                            "guard": {"condition": "ok == true", "on_false": "skip"},
                            "schema": [{"id": "data", "type": "object"}],
                        },
                    ),
                    (
                        "middle",
                        {
                            "model_vendor": "openai",
                            "context_scope": {
                                "observe": ["guarded.data"],
                                "passthrough": passthrough,
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

            assert apply_guard_nullable_schema_fixes(action_configs) == [], passthrough

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

"""Regression tests for context scope application.

Covers observe, passthrough, drop, format, merge, gating, and edge cases.
"""

from unittest.mock import patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_application import (
    apply_context_scope,
    format_llm_context,
    merge_passthrough_fields,
)


class TestDropWildcard:
    def test_wildcard_clears_entire_namespace(self):
        """drop: ['dep.*'] removes ALL fields from the dep namespace.

        When combined with observe (required for prompt_context access), the
        dropped fields must not appear.
        """
        field_context = {"dep": {"api_key": "secret", "name": "test", "value": "data"}}
        prompt_context, _, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"drop": ["dep.*"], "observe": ["dep.*"]},
            action_name="test_action",
        )
        # dep namespace exists but all fields were dropped before observe
        assert prompt_context.get("dep", {}) == {}

    def test_exact_field_drop_removes_only_that_field(self):
        """drop: ['dep.api_key'] removes only api_key from dep namespace."""
        field_context = {"dep": {"api_key": "secret", "name": "test"}}
        prompt_context, _, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"drop": ["dep.api_key"], "observe": ["dep.*"]},
            action_name="test_action",
        )
        assert "api_key" not in prompt_context.get("dep", {})
        assert prompt_context["dep"]["name"] == "test"

    def test_wildcard_on_empty_namespace_warns(self):
        """drop: ['dep.*'] on empty namespace logs a warning, no crash."""
        field_context = {"dep": {}}
        with patch("agent_actions.prompt.context.scope_application.logger") as mock_logger:
            apply_context_scope(
                field_context=field_context,
                context_scope={"drop": ["dep.*"]},
                action_name="test_action",
            )
        mock_logger.warning.assert_called()
        args = mock_logger.warning.call_args[0]
        assert "matched zero fields" in args[0]

    def test_missing_field_warns(self):
        """drop: ['dep.missing'] when field absent logs a warning, no crash."""
        field_context = {"dep": {"other": "value"}}
        with patch("agent_actions.prompt.context.scope_application.logger") as mock_logger:
            apply_context_scope(
                field_context=field_context,
                context_scope={"drop": ["dep.missing"]},
                action_name="test_action",
            )
        mock_logger.warning.assert_called()
        args = mock_logger.warning.call_args[0]
        assert "matched zero fields" in args[0]

    def test_missing_namespace_warns(self):
        """drop: ['ghost.*'] when namespace absent logs a warning, no crash."""
        field_context = {"dep": {"key": "value"}}
        with patch("agent_actions.prompt.context.scope_application.logger") as mock_logger:
            apply_context_scope(
                field_context=field_context,
                context_scope={"drop": ["ghost.*"]},
                action_name="test_action",
            )
        mock_logger.warning.assert_called()
        args = mock_logger.warning.call_args[0]
        assert "matched zero fields" in args[0]

    def test_non_dict_namespace_warns(self):
        """Namespace exists but is a non-dict value (e.g. a string) — warns, no crash."""
        field_context = {"dep": "a_string_not_a_dict"}
        with patch("agent_actions.prompt.context.scope_application.logger") as mock_logger:
            apply_context_scope(
                field_context=field_context,
                context_scope={"drop": ["dep.field"]},
                action_name="test_action",
            )
        mock_logger.warning.assert_called()
        args = mock_logger.warning.call_args[0]
        assert "not a dict" in args[0]

    def test_malformed_drop_ref_does_not_crash(self):
        """Malformed drop directive (no dot) is caught, logged, field not removed."""
        field_context = {"dep": {"api_key": "secret"}}
        # "noperiod" has no dot — parse_field_reference raises ValueError
        prompt_context, _, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"drop": ["noperiod"], "observe": ["dep.*"]},
            action_name="test_action",
        )
        # Field must NOT be removed (drop failed to parse — safe failure)
        assert prompt_context["dep"]["api_key"] == "secret"

    def test_wildcard_drop_then_observe_specific_field_raises(self):
        """After drop: ['dep.*'], observe: ['dep.name'] must raise — all fields gone."""
        field_context = {"dep": {"api_key": "secret", "name": "test", "value": "data"}}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=field_context,
                context_scope={"drop": ["dep.*"], "observe": ["dep.name"]},
                action_name="test_action",
            )

    def test_drop_then_observe_wildcard_excludes_dropped_field(self):
        """Existing security test: drop + observe wildcard must not leak dropped field."""
        field_context = {"dep": {"api_key": "sk-secret-123", "name": "test", "value": "safe_data"}}
        context_scope = {
            "drop": ["dep.api_key"],
            "observe": ["dep.*"],
        }
        _, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope=context_scope,
            action_name="test_action",
        )
        assert "api_key" not in llm_context.get("dep", {})
        assert "name" in llm_context["dep"]
        assert "value" in llm_context["dep"]


class TestFalsyFieldPassthrough:
    """G-2: falsy values (0, "", False, None) must not be silently dropped."""

    def test_observe_includes_zero_value(self):
        """observe: field with value 0 must appear in llm_context."""
        field_context = {"dep": {"score": 0}}
        _, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"observe": ["dep.score"]},
            action_name="test_action",
        )
        assert llm_context["dep"]["score"] == 0

    def test_observe_includes_empty_string(self):
        """observe: field with value "" must appear in llm_context."""
        field_context = {"dep": {"label": ""}}
        _, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"observe": ["dep.label"]},
            action_name="test_action",
        )
        assert llm_context["dep"]["label"] == ""

    def test_passthrough_includes_zero_value(self):
        """passthrough: field with value 0 must appear in passthrough_fields."""
        field_context = {"dep": {"count": 0}}
        _, _, passthrough = apply_context_scope(
            field_context=field_context,
            context_scope={"passthrough": ["dep.count"]},
            action_name="test_action",
        )
        assert passthrough["dep"]["count"] == 0

    def test_passthrough_includes_false_value(self):
        """passthrough: field with value False must appear in passthrough_fields."""
        field_context = {"dep": {"enabled": False}}
        _, _, passthrough = apply_context_scope(
            field_context=field_context,
            context_scope={"passthrough": ["dep.enabled"]},
            action_name="test_action",
        )
        assert passthrough["dep"]["enabled"] is False

    def test_missing_field_raises_error(self):
        """Fields truly absent from context must raise ConfigurationError."""
        field_context = {"dep": {"other": "value"}}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=field_context,
                context_scope={"observe": ["dep.missing"]},
                action_name="test_action",
            )

    def test_observe_includes_explicit_none_value(self):
        """G-2 boundary: field whose value IS None must still appear in llm_context.
        None is a valid observed value — only a missing field should be excluded."""
        field_context = {"dep": {"nullable_field": None}}
        _, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"observe": ["dep.nullable_field"]},
            action_name="test_action",
        )
        assert llm_context["dep"]["nullable_field"] is None

    def test_passthrough_nested_path_missing_field_raises(self):
        """G-2 nested-path: a truly missing nested field must raise ConfigurationError."""
        field_context = {"dep": {"top": {"exists": 1}}}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=field_context,
                context_scope={"passthrough": ["dep.top.missing"]},
                action_name="test_action",
            )


class TestAbsentNamespace:
    """Tests for observe/passthrough on entirely absent namespaces."""

    def test_observe_absent_namespace_raises(self):
        """Observing a field from a namespace that doesn't exist raises."""
        field_context = {"dep": {"field1": "value"}}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=field_context,
                context_scope={"observe": ["ghost.field"]},
                action_name="test_action",
            )

    def test_passthrough_absent_namespace_raises(self):
        """Passthrough from a namespace that doesn't exist raises."""
        field_context = {"dep": {"field1": "value"}}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=field_context,
                context_scope={"passthrough": ["ghost.field"]},
                action_name="test_action",
            )


class TestVersionedActionObserve:
    """Tests for versioned actions after early expansion.

    After normalization, observe: [action.*] becomes
    observe: [action_1.*, action_2.*, action_3.*].
    These are standard wildcard refs — no special handling needed.

    Regression: github.com/Muizzkolapo/agent-actions/issues/193
    """

    def test_observe_concrete_versioned_wildcards(self):
        """observe: ['action_1.*', 'action_2.*', 'action_3.*'] works like regular wildcards."""
        field_context = {
            "action_1": {"questions": ["q1"], "answers": ["a1"]},
            "action_2": {"questions": ["q2"], "answers": ["a2"]},
            "action_3": {"questions": ["q3"], "answers": ["a3"]},
        }
        prompt_context, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"observe": ["action_1.*", "action_2.*", "action_3.*"]},
            action_name="consumer",
        )
        # Each version is a separate namespace in llm_context — no data loss
        assert "questions" in llm_context["action_1"]
        assert "questions" in llm_context["action_2"]
        assert "questions" in llm_context["action_3"]
        assert "action_1" in prompt_context
        assert "action_2" in prompt_context
        assert "action_3" in prompt_context

    def test_mixed_versioned_and_regular_observe(self):
        field_context = {
            "version_1": {"a": 1},
            "version_2": {"b": 2},
            "regular_dep": {"c": 3},
        }
        prompt_context, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"observe": ["version_1.*", "version_2.*", "regular_dep.*"]},
            action_name="consumer",
        )
        assert llm_context == {
            "version_1": {"a": 1},
            "version_2": {"b": 2},
            "regular_dep": {"c": 3},
        }
        assert "version_1" in prompt_context
        assert "version_2" in prompt_context
        assert "regular_dep" in prompt_context

    def test_drop_then_observe_versioned(self):
        field_context = {
            "action_1": {"secret": "s1", "name": "n1"},
            "action_2": {"secret": "s2", "name": "n2"},
        }
        prompt_context, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope={
                "drop": ["action_1.*", "action_2.*"],
                "observe": ["action_1.*", "action_2.*"],
            },
            action_name="test",
        )
        assert llm_context == {}

    def test_gating_includes_versioned_excludes_unrelated(self):
        field_context = {
            "action_1": {"f1": "v1"},
            "action_2": {"f2": "v2"},
            "unrelated": {"x": "y"},
        }
        prompt_context, _, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"observe": ["action_1.*", "action_2.*"]},
            action_name="consumer",
        )
        assert "action_1" in prompt_context
        assert "action_2" in prompt_context
        assert "unrelated" not in prompt_context

    def test_versioned_same_field_names_no_data_loss(self):
        """Core regression: versioned actions with identical field names must all be preserved."""
        field_context = {
            "voter_1": {"score": 8, "reasoning": "good"},
            "voter_2": {"score": 7, "reasoning": "decent"},
            "voter_3": {"score": 9, "reasoning": "great"},
        }
        _, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"observe": ["voter_1.*", "voter_2.*", "voter_3.*"]},
            action_name="aggregate",
        )
        assert llm_context["voter_1"]["score"] == 8
        assert llm_context["voter_2"]["score"] == 7
        assert llm_context["voter_3"]["score"] == 9
        assert llm_context["voter_1"]["reasoning"] == "good"
        assert llm_context["voter_2"]["reasoning"] == "decent"
        assert llm_context["voter_3"]["reasoning"] == "great"


class TestObserveNamespacing:
    """llm_context is namespaced: {action_name: {field: value}}."""

    def test_single_action_wildcard(self):
        fc = {"dep": {"name": "test", "value": 42}}
        _, lc, _ = apply_context_scope(fc, {"observe": ["dep.*"]})
        assert lc == {"dep": {"name": "test", "value": 42}}

    def test_specific_field_namespaced(self):
        fc = {"dep": {"score": 5, "extra": "x"}}
        _, lc, _ = apply_context_scope(fc, {"observe": ["dep.score"]})
        assert lc == {"dep": {"score": 5}}

    def test_multiple_fields_same_namespace(self):
        fc = {"dep": {"a": 1, "b": 2, "c": 3}}
        _, lc, _ = apply_context_scope(fc, {"observe": ["dep.a", "dep.b"]})
        assert lc == {"dep": {"a": 1, "b": 2}}

    def test_nested_dot_path(self):
        fc = {"dep": {"outer": {"inner": 42}}}
        _, lc, _ = apply_context_scope(fc, {"observe": ["dep.outer.inner"]})
        assert lc["dep"]["outer.inner"] == 42

    def test_wildcard_absent_namespace_lenient(self):
        fc = {"dep": {"f": 1}}
        _, lc, _ = apply_context_scope(fc, {"observe": ["ghost.*", "dep.*"]})
        assert "ghost" not in lc
        assert lc["dep"]["f"] == 1

    def test_specific_field_absent_namespace_raises(self):
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope({"dep": {"f": 1}}, {"observe": ["ghost.field"]})

    def test_empty_observe_empty_llm_context(self):
        _, lc, _ = apply_context_scope({"dep": {"f": 1}}, {"passthrough": ["dep.f"]})
        assert lc == {}


class TestPassthroughNamespacing:
    """passthrough_fields is namespaced: {action_name: {field: value}}."""

    def test_specific_field_namespaced(self):
        fc = {"dep": {"id": "rec-1", "text": "hello"}}
        _, _, pt = apply_context_scope(fc, {"passthrough": ["dep.id"]})
        assert pt == {"dep": {"id": "rec-1"}}

    def test_wildcard_namespaced(self):
        fc = {"dep": {"a": 1, "b": 2}}
        _, _, pt = apply_context_scope(fc, {"passthrough": ["dep.*"]})
        assert pt == {"dep": {"a": 1, "b": 2}}

    def test_version_collision_preserved(self):
        fc = {"v_1": {"id": "a"}, "v_2": {"id": "b"}, "v_3": {"id": "c"}}
        _, _, pt = apply_context_scope(fc, {"passthrough": ["v_1.*", "v_2.*", "v_3.*"]})
        assert pt["v_1"]["id"] == "a"
        assert pt["v_2"]["id"] == "b"
        assert pt["v_3"]["id"] == "c"

    def test_falsy_zero(self):
        fc = {"dep": {"count": 0}}
        _, _, pt = apply_context_scope(fc, {"passthrough": ["dep.count"]})
        assert pt["dep"]["count"] == 0

    def test_falsy_false(self):
        fc = {"dep": {"enabled": False}}
        _, _, pt = apply_context_scope(fc, {"passthrough": ["dep.enabled"]})
        assert pt["dep"]["enabled"] is False

    def test_missing_field_raises(self):
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope({"dep": {"a": 1}}, {"passthrough": ["dep.missing"]})

    def test_missing_namespace_raises(self):
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope({"dep": {"a": 1}}, {"passthrough": ["ghost.field"]})

    def test_no_cross_contamination_with_observe(self):
        fc = {"dep": {"obs": "o", "pt": "p"}}
        _, lc, pt = apply_context_scope(fc, {"observe": ["dep.obs"], "passthrough": ["dep.pt"]})
        assert lc == {"dep": {"obs": "o"}}
        assert pt == {"dep": {"pt": "p"}}
        assert "pt" not in lc.get("dep", {})
        assert "obs" not in pt.get("dep", {})


class TestFormatAndMerge:
    """format_llm_context and merge_passthrough_fields."""

    def test_format_namespaced(self):
        lc = {"dep_1": {"score": 8}, "dep_2": {"score": 7}}
        text = format_llm_context(lc)
        assert text.startswith("Additional context:")
        assert "dep_1.score:" in text
        assert "dep_2.score:" in text

    def test_format_empty(self):
        assert format_llm_context({}) == ""

    def test_format_single_namespace(self):
        text = format_llm_context({"dep": {"name": "test"}})
        assert "dep.name:" in text

    def test_merge_namespaced_into_content(self):
        response = [{"content": {"result": "ok"}}]
        pt = {"dep": {"id": "rec-1"}}
        merged = merge_passthrough_fields(response, pt)
        assert merged[0]["content"]["dep"] == {"id": "rec-1"}
        assert merged[0]["content"]["result"] == "ok"

    def test_merge_empty_passthrough_unchanged(self):
        response = [{"content": {"r": 1}}]
        assert merge_passthrough_fields(response, {}) == response

    def test_merge_into_flat_response(self):
        response = [{"result": "ok"}]
        pt = {"dep": {"id": "rec-1"}}
        merged = merge_passthrough_fields(response, pt)
        assert merged[0]["dep"] == {"id": "rec-1"}
        assert merged[0]["result"] == "ok"


class TestDropVersioned:
    """Drop directives on versioned actions."""

    def test_drop_specific_field_on_versioned(self):
        fc = {"v_1": {"secret": "s", "name": "n"}, "v_2": {"secret": "s", "name": "n"}}
        _, lc, _ = apply_context_scope(
            fc,
            {"drop": ["v_1.secret", "v_2.secret"], "observe": ["v_1.*", "v_2.*"]},
            action_name="t",
        )
        assert "secret" not in lc.get("v_1", {})
        assert "secret" not in lc.get("v_2", {})
        assert lc["v_1"]["name"] == "n"
        assert lc["v_2"]["name"] == "n"


class TestAllDirectivesCombined:
    """End-to-end with all three directives."""

    def test_drop_observe_passthrough_together(self):
        fc = {
            "source": {"text": "hello", "api_key": "secret"},
            "dep": {"score": 9, "extra": "x"},
        }
        pc, lc, pt = apply_context_scope(
            fc,
            {
                "drop": ["source.api_key"],
                "observe": ["source.text"],
                "passthrough": ["dep.score"],
            },
            action_name="t",
        )
        assert lc == {"source": {"text": "hello"}}
        assert pt == {"dep": {"score": 9}}
        assert "api_key" not in pc.get("source", {})

    def test_observe_passthrough_same_namespace(self):
        fc = {"dep": {"obs": "o", "pt": "p"}}
        _, lc, pt = apply_context_scope(fc, {"observe": ["dep.obs"], "passthrough": ["dep.pt"]})
        assert lc == {"dep": {"obs": "o"}}
        assert pt == {"dep": {"pt": "p"}}

    def test_seed_data_in_prompt_context(self):
        fc = {"dep": {"f": 1}}
        static = {"exam": {"name": "Test"}}
        pc, lc, _ = apply_context_scope(fc, {"observe": ["dep.f"]}, static_data=static)
        assert pc["seed"] == {"exam": {"name": "Test"}}
        assert "seed" not in lc

    def test_framework_namespaces_always_available(self):
        fc = {"dep": {"f": 1}, "version": {"i": 1}, "workflow": {"name": "test"}}
        pc, lc, _ = apply_context_scope(fc, {"observe": ["dep.f"]})
        assert "version" in pc
        assert "workflow" in pc
        assert "version" not in lc
        assert "workflow" not in lc

    def test_empty_field_context(self):
        pc, lc, pt = apply_context_scope({}, {})
        assert pc == {} and lc == {} and pt == {}

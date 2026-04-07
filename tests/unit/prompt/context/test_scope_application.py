"""Regression tests for A-3/G-1: drop wildcard and zero-match warnings."""

from unittest.mock import patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_application import apply_context_scope


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
        assert "api_key" not in llm_context
        assert "name" in llm_context
        assert "value" in llm_context


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
        assert "score" in llm_context
        assert llm_context["score"] == 0

    def test_observe_includes_empty_string(self):
        """observe: field with value "" must appear in llm_context."""
        field_context = {"dep": {"label": ""}}
        _, llm_context, _ = apply_context_scope(
            field_context=field_context,
            context_scope={"observe": ["dep.label"]},
            action_name="test_action",
        )
        assert "label" in llm_context
        assert llm_context["label"] == ""

    def test_passthrough_includes_zero_value(self):
        """passthrough: field with value 0 must appear in passthrough_fields."""
        field_context = {"dep": {"count": 0}}
        _, _, passthrough = apply_context_scope(
            field_context=field_context,
            context_scope={"passthrough": ["dep.count"]},
            action_name="test_action",
        )
        assert "count" in passthrough
        assert passthrough["count"] == 0

    def test_passthrough_includes_false_value(self):
        """passthrough: field with value False must appear in passthrough_fields."""
        field_context = {"dep": {"enabled": False}}
        _, _, passthrough = apply_context_scope(
            field_context=field_context,
            context_scope={"passthrough": ["dep.enabled"]},
            action_name="test_action",
        )
        assert "enabled" in passthrough
        assert passthrough["enabled"] is False

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
        assert "nullable_field" in llm_context
        assert llm_context["nullable_field"] is None

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
        assert "questions" in llm_context
        assert "answers" in llm_context
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
        assert llm_context == {"a": 1, "b": 2, "c": 3}
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

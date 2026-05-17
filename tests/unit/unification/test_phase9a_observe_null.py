"""Phase 9a: Guard/Observe null safety tests — U-4.2.

Tests that observe resolves missing fields from present namespaces to None
(matching guard semantics) instead of raising RecordContextError.

Preflight still catches config typos. Only VALID references to
legitimately-missing data resolve to null at runtime.
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_application import apply_context_scope


def _make_field_context(**namespaces):
    """Build a field_context dict from namespace kwargs."""
    return dict(namespaces)


class TestObserveNullSafety:
    """U-4.2: Observe must resolve missing fields to None, not throw."""

    def test_observe_missing_field_returns_none(self):
        """Observing a field that doesn't exist in a present namespace → None, not error."""
        fc = _make_field_context(upstream_step={"field_a": "value"})
        _prompt_ctx, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["upstream_step.field_b"]},
            action_name="downstream",
        )
        assert llm_ctx["upstream_step"]["field_b"] is None

    def test_observe_missing_field_preserves_present_fields(self):
        """Missing field returns None without affecting existing field resolution."""
        fc = _make_field_context(dep={"real_field": "real_value"})
        _prompt_ctx, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["dep.real_field", "dep.ghost_field"]},
            action_name="downstream",
        )
        assert llm_ctx["dep"]["real_field"] == "real_value"
        assert llm_ctx["dep"]["ghost_field"] is None

    def test_observe_undeclared_namespace_still_raises(self):
        """Namespace not in field_context at all → still errors (config bug)."""
        fc = _make_field_context(dep={"f": 1})
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["ghost.field"]},
                action_name="downstream",
            )

    def test_observe_null_namespace_still_returns_none(self):
        """Null namespace (guard-skipped) → None, unchanged from existing behavior."""
        fc = _make_field_context(skipped=None)
        _prompt_ctx, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped.field"]},
            action_name="downstream",
        )
        assert llm_ctx["skipped"]["field"] is None

    def test_guard_and_observe_agree_on_missing(self):
        """Guard returns None for missing field; observe must do the same.

        Guards treat missing fields as 'condition not matched' (falsy/None).
        Observe must resolve the same field to None — not throw.
        """
        fc = _make_field_context(ns={"existing": "value"})
        # Observe a field that doesn't exist → should be None (matching guard)
        _prompt_ctx, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["ns.missing"]},
            action_name="downstream",
        )
        observe_result = llm_ctx["ns"]["missing"]
        assert observe_result is None

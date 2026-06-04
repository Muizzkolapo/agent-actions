"""Observe missing field behavior tests.

Tests that observe correctly handles missing fields:
- Null namespace (guard-skipped) → resolves to None (safe)
- Present namespace, missing field → raises RecordContextError (prevents
  garbage LLM output from None injection)
- Absent namespace → raises RecordContextError (config bug)

Passthrough still resolves missing fields to None (matching guard semantics)
since passthrough fields are not rendered into prompts.
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_application import apply_context_scope


def _make_field_context(**namespaces):
    """Build a field_context dict from namespace kwargs."""
    return dict(namespaces)


class TestObserveNullSafety:
    """Observe raises for missing fields in present namespaces."""

    def test_observe_missing_field_raises(self):
        """Observing a field that doesn't exist in a present namespace → raises."""
        fc = _make_field_context(upstream_step={"field_a": "value"})
        with pytest.raises(ConfigurationError, match="not found in namespace"):
            apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["upstream_step.field_b"]},
                action_name="downstream",
            )

    def test_observe_missing_field_raises_even_with_present_fields(self):
        """Missing field raises even when other fields in the namespace exist."""
        fc = _make_field_context(dep={"real_field": "real_value"})
        with pytest.raises(ConfigurationError, match="not found in namespace"):
            apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["dep.real_field", "dep.ghost_field"]},
                action_name="downstream",
            )

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

    def test_passthrough_missing_field_returns_none(self):
        """Passthrough still resolves missing field to None (not rendered in prompts)."""
        fc = _make_field_context(ns={"existing": "value"})
        _prompt_ctx, _llm_ctx, pt = apply_context_scope(
            field_context=fc,
            context_scope={"passthrough": ["ns.missing"]},
            action_name="downstream",
        )
        assert pt["ns"]["missing"] is None

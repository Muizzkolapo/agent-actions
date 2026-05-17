"""Phase 9b: Observe Skipped Namespace — U-4.1.

When a dependency namespace is skipped (conditional HITL, optional LLM
fallback), observe must resolve all fields from that namespace to None
instead of crashing.  The ``NullNamespace`` sentinel carries the *reason*
the namespace is absent so downstream code can introspect it.

Key invariant: ``NullNamespace(reason="skipped")`` in field_context →
observe/passthrough fields resolve to ``None``.  A namespace that is
*absent entirely* from field_context is still a configuration error.
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.null_namespace import NullNamespace
from agent_actions.prompt.context.scope_application import apply_context_scope


def _make_field_context(**namespaces):
    """Build a field_context dict from namespace kwargs."""
    return dict(namespaces)


# ── Observe: NullNamespace sentinel ──────────────────────────────────


class TestObserveSkippedNamespace:
    """U-4.1: Skipped namespace must be observable as null, not crash."""

    def test_observe_field_from_skipped_namespace_returns_none(self):
        """Observing a field from a NullNamespace(reason='skipped') → None."""
        fc = _make_field_context(
            skipped_step=NullNamespace(reason="skipped"),
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped_step.any_field"]},
            action_name="downstream",
        )
        assert llm_ctx["skipped_step"]["any_field"] is None

    def test_observe_multiple_fields_from_skipped_namespace(self):
        """All fields from a skipped namespace resolve to None."""
        fc = _make_field_context(
            skipped_step=NullNamespace(reason="skipped"),
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": [
                "skipped_step.field_a",
                "skipped_step.field_b",
                "skipped_step.field_c",
            ]},
            action_name="downstream",
        )
        assert llm_ctx["skipped_step"] == {
            "field_a": None,
            "field_b": None,
            "field_c": None,
        }

    def test_observe_wildcard_on_skipped_namespace_is_empty(self):
        """Wildcard observe on NullNamespace → no fields extracted (safe)."""
        fc = _make_field_context(
            skipped_step=NullNamespace(reason="skipped"),
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped_step.*"]},
            action_name="downstream",
        )
        assert "skipped_step" not in llm_ctx

    def test_observe_from_missing_namespace_still_errors(self):
        """Namespace absent from field_context entirely → ConfigurationError."""
        fc = _make_field_context(present={"f": 1})
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["nonexistent_step.field"]},
                action_name="downstream",
            )

    def test_mixed_skipped_and_present_namespaces(self):
        """Normal namespace resolves normally; skipped resolves to None."""
        fc = _make_field_context(
            present={"score": 95},
            skipped_step=NullNamespace(reason="skipped"),
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["present.score", "skipped_step.status"]},
            action_name="downstream",
        )
        assert llm_ctx["present"]["score"] == 95
        assert llm_ctx["skipped_step"]["status"] is None


# ── Passthrough: NullNamespace sentinel ──────────────────────────────


class TestPassthroughSkippedNamespace:
    """Passthrough from NullNamespace must also resolve to None."""

    def test_passthrough_field_from_skipped_namespace(self):
        """Passthrough from skipped namespace → None."""
        fc = _make_field_context(
            skipped_step=NullNamespace(reason="skipped"),
        )
        _, _, pt = apply_context_scope(
            field_context=fc,
            context_scope={"passthrough": ["skipped_step.trace_id"]},
            action_name="downstream",
        )
        assert pt["skipped_step"]["trace_id"] is None


# ── Drop: NullNamespace sentinel ─────────────────────────────────────


class TestDropSkippedNamespace:
    """Drop on NullNamespace must not crash."""

    def test_drop_on_skipped_namespace_no_crash(self):
        """Drop on NullNamespace → no crash, valid return."""
        fc = _make_field_context(
            skipped_step=NullNamespace(reason="skipped"),
        )
        prompt_ctx, llm_ctx, pt = apply_context_scope(
            field_context=fc,
            context_scope={"drop": ["skipped_step.field"]},
            action_name="downstream",
        )
        assert isinstance(prompt_ctx, dict)
        assert isinstance(llm_ctx, dict)
        assert isinstance(pt, dict)


# ── Gating: NullNamespace sentinel ───────────────────────────────────


class TestGatingSkippedNamespace:
    """NullNamespace passes through the prompt_context gating phase."""

    def test_skipped_namespace_passes_through_gate(self):
        """NullNamespace in allowed set passes gating."""
        fc = _make_field_context(
            skipped_step=NullNamespace(reason="skipped"),
            present={"f": 1},
        )
        prompt_ctx, _, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped_step.status", "present.f"]},
            action_name="downstream",
        )
        # NullNamespace should be in prompt_context (for template rendering awareness)
        assert "skipped_step" in prompt_ctx
        assert prompt_ctx["present"]["f"] == 1


# ── NullNamespace reason introspection ───────────────────────────────


class TestNullNamespaceReason:
    """The reason attribute is accessible for downstream introspection."""

    def test_reason_attribute(self):
        """NullNamespace carries the reason for null-ness."""
        ns = NullNamespace(reason="skipped")
        assert ns.reason == "skipped"

    def test_falsy(self):
        """NullNamespace is falsy (like None)."""
        ns = NullNamespace(reason="skipped")
        assert not ns

    def test_equality(self):
        """NullNamespace with same reason are equal."""
        assert NullNamespace(reason="skipped") == NullNamespace(reason="skipped")
        assert NullNamespace(reason="skipped") != NullNamespace(reason="filtered")


# ── Combined directives on NullNamespace ─────────────────────────────


class TestCombinedDirectivesSkippedNamespace:
    """Interaction of multiple directives when namespace is NullNamespace."""

    def test_observe_and_passthrough_both_null_safe(self):
        """Both observe and passthrough on skipped namespace yield None."""
        fc = _make_field_context(
            skipped_step=NullNamespace(reason="skipped"),
        )
        _, llm_ctx, pt = apply_context_scope(
            field_context=fc,
            context_scope={
                "observe": ["skipped_step.status"],
                "passthrough": ["skipped_step.trace_id"],
            },
            action_name="downstream",
        )
        assert llm_ctx["skipped_step"]["status"] is None
        assert pt["skipped_step"]["trace_id"] is None

    def test_drop_then_observe_on_skipped_no_crash(self):
        """Drop + observe on NullNamespace: drop is no-op, observe yields None."""
        fc = _make_field_context(
            skipped_step=NullNamespace(reason="skipped"),
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={
                "drop": ["skipped_step.secret"],
                "observe": ["skipped_step.status"],
            },
            action_name="downstream",
        )
        assert llm_ctx["skipped_step"]["status"] is None

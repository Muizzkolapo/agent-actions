"""Tests for enriched runtime errors when filter+fan-in produces null namespaces.

Spec 415 Option C: instead of bare 'NoneType has no attribute', errors should
name the filtered namespace, alternate dependency path, and remediation options.
"""

import logging

import pytest

from agent_actions.errors.operations import TemplateVariableError
from agent_actions.prompt.context.scope_application import apply_context_scope
from agent_actions.prompt.service import PromptPreparationService


def _make_field_context(**namespaces):
    """Build a field_context dict from namespace kwargs."""
    return dict(namespaces)


# ── scope_application: enriched warning log on null namespace at fan-in ──


class TestResolveNullNamespaceWarning:
    """_resolve_missing_field logs warning with alt deps when namespace is null at fan-in."""

    @pytest.fixture(autouse=True)
    def _enable_propagation(self):
        """Ensure the agent_actions logger propagates to root so caplog captures records."""
        aa_logger = logging.getLogger("agent_actions")
        original = aa_logger.propagate
        aa_logger.propagate = True
        yield
        aa_logger.propagate = original

    def test_null_namespace_with_alt_dep_logs_warning(self, caplog):
        """Null namespace + alternate dep present -> warning-level log with alt dep name."""
        fc = _make_field_context(
            filtered_action=None,
            other_dep={"score": 42},
        )
        with caplog.at_level(logging.WARNING):
            _, llm_ctx, _ = apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["filtered_action.field_a"]},
                action_name="consumer",
            )

        # Field resolves to None (existing null-safe behavior).
        assert llm_ctx["filtered_action"]["field_a"] is None

        # Warning log contains enriched context.
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_logs) >= 1
        msg = warning_logs[0].message
        assert "filtered_action" in msg
        assert "other_dep" in msg
        assert "NULL-NAMESPACE" in msg

    def test_null_namespace_without_alt_dep_logs_debug(self, caplog):
        """Null namespace with no alternate deps -> debug-level log (no fan-in signal)."""
        fc = _make_field_context(filtered_action=None)
        with caplog.at_level(logging.DEBUG):
            _, llm_ctx, _ = apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["filtered_action.field_a"]},
                action_name="consumer",
            )

        assert llm_ctx["filtered_action"]["field_a"] is None

        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_logs) == 0

        debug_logs = [r for r in caplog.records if "NULL-SAFE" in r.message]
        assert len(debug_logs) >= 1

    def test_warning_includes_remediation_hints(self, caplog):
        """Warning message includes remediation suggestions."""
        fc = _make_field_context(
            filtered_action=None,
            alt_dep_a={"data": "ok"},
            alt_dep_b={"data": "ok"},
        )
        with caplog.at_level(logging.WARNING):
            apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["filtered_action.field_a"]},
                action_name="consumer",
            )

        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
        msg = warning_logs[0].message
        assert "guard" in msg.lower() or "null-safe" in msg.lower()
        assert "filtered_action.*" in msg


# ── service.py: TemplateVariableError with null_namespace_hints ──────


class TestTemplateNullNamespaceError:
    """Jinja render errors include null_namespace_hints when namespace is None."""

    def test_nonetype_attribute_error_includes_null_namespace_hints(self):
        """Template {{ action.field }} on null namespace -> error has null_namespace_hints."""
        prompt_context = {
            "filtered_action": None,
            "other_dep": {"score": 42},
        }
        raw_prompt = "Score: {{ other_dep.score }}, Letter: {{ filtered_action.answer_letter }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="write_scenario_question",
            )

        err = exc_info.value
        assert err.null_namespace_hints
        assert "filtered_action" in err.null_namespace_hints
        hint = err.null_namespace_hints["filtered_action"]
        assert "other_dep" in hint["alternate_deps"]
        assert "filtered" in hint["remediation"].lower()

    def test_error_message_includes_remediation(self):
        """The error message itself contains remediation text."""
        prompt_context = {
            "filtered_action": None,
            "other_dep": {"score": 42},
        }
        raw_prompt = "{{ filtered_action.answer_letter }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="consumer",
            )

        msg = str(exc_info.value)
        assert "null" in msg.lower()
        assert "guard-filtered" in msg.lower() or "filtered" in msg.lower()

    def test_normal_undefined_error_has_no_null_hints(self):
        """Regular undefined variable error -> no null_namespace_hints."""
        prompt_context = {
            "dep_a": {"score": 42},
        }
        raw_prompt = "{{ nonexistent_var.field }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="consumer",
            )

        err = exc_info.value
        assert not err.null_namespace_hints

    def test_context_dict_includes_null_namespace_hints(self):
        """The error context dict contains null_namespace_hints for downstream consumers."""
        prompt_context = {
            "filtered_ns": None,
            "good_ns": {"val": 1},
        }
        raw_prompt = "{{ filtered_ns.some_field }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="consumer",
            )

        err = exc_info.value
        assert "null_namespace_hints" in err.context
        assert "filtered_ns" in err.context["null_namespace_hints"]

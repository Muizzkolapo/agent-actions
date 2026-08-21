"""Tests for enriched runtime errors when filter+fan-in produces null namespaces.

Spec 415 Option C: instead of bare 'NoneType has no attribute', errors should
name the filtered namespace, alternate dependency path, and remediation options.
"""

import logging

import pytest

from agent_actions.errors.operations import TemplateVariableError
from agent_actions.prompt.context.null_namespace import SKIPPED_NAMESPACE
from agent_actions.prompt.context.scope_application import apply_context_scope
from agent_actions.prompt.service import PromptPreparationService


def _make_field_context(**namespaces):
    """Build a field_context dict from namespace kwargs."""
    return dict(namespaces)


# ── scope_application: null namespace resolves to None (debug only) ───


class TestResolveNullNamespaceDebugLog:
    """_resolve_missing_field logs at DEBUG on the success path — never WARNING.

    Warnings about null-namespace hazards belong in the preflight static
    analyzer (_check_filter_fanin_observe_hazard), not in the per-field
    resolution function that fires N×M times per workflow.
    """

    @pytest.fixture(autouse=True)
    def _enable_propagation(self):
        """Ensure the agent_actions logger propagates to root so caplog captures records."""
        aa_logger = logging.getLogger("agent_actions")
        original = aa_logger.propagate
        aa_logger.propagate = True
        yield
        aa_logger.propagate = original

    def test_null_namespace_resolves_to_none_with_debug_log(self, caplog):
        """Null namespace with alt deps present -> field resolves to None, logs at DEBUG."""
        fc = _make_field_context(
            filtered_action=None,
            other_dep={"score": 42},
        )
        with caplog.at_level(logging.DEBUG):
            _, llm_ctx, _ = apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["filtered_action.field_a"]},
                action_name="consumer",
            )

        assert llm_ctx["filtered_action"]["field_a"] is None

        # No warnings on the success path.
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_logs) == 0

        debug_logs = [r for r in caplog.records if "NULL-SAFE" in r.message]
        assert len(debug_logs) >= 1


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

    def test_error_message_appends_remediation_to_original(self):
        """Error message includes both the original missing-var text AND remediation."""
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
        # Original message preserved.
        assert "undefined variables" in msg.lower()
        # Remediation appended.
        assert "null" in msg.lower()
        assert "null-safe" in msg.lower()

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

    def test_typo_on_non_null_ns_with_null_ns_coexisting_no_false_blame(self):
        """Typo on a non-null namespace while a null namespace coexists -> no false blame.

        This is the key false-positive regression test: dep_a is None but
        the error is {{ good.nonexistent_field }} — dep_a should NOT be blamed.
        """
        prompt_context = {
            "dep_a": None,
            "good": {"x": 1},
        }
        raw_prompt = "{{ good.nonexistent_field }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="consumer",
            )

        err = exc_info.value
        # dep_a is None but was never accessed — must NOT appear in hints.
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


# ── service.py: the NullNamespace sentinel gets the same hints as None ──


class TestTemplateNullNamespaceSentinelError:
    """Spec 595: guard-skipped namespaces reach the renderer as the
    ``NullNamespace`` sentinel, not legacy ``None``. Jinja names the object
    (``'...NullNamespace object' has no attribute 'x'``), so a hint gated on
    the literal ``'None'`` never fired on the shape production actually builds.
    """

    def test_sentinel_attribute_error_includes_null_namespace_hints(self):
        """Production shape: {{ ns.field }} on SKIPPED_NAMESPACE -> hints name ns."""
        prompt_context = {
            "auto_review_quality": SKIPPED_NAMESPACE,
            "other_dep": {"score": 42},
        }
        raw_prompt = "Score: {{ other_dep.score }}, T: {{ auto_review_quality.telegraph_score }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="write_scenario_question",
            )

        err = exc_info.value
        assert err.null_namespace_hints
        assert "auto_review_quality" in err.null_namespace_hints
        hint = err.null_namespace_hints["auto_review_quality"]
        assert "other_dep" in hint["alternate_deps"]
        assert "skipped" in hint["remediation"].lower()

    def test_sentinel_message_appends_remediation(self):
        """The rendered error text carries the null-safe remediation, as None does."""
        prompt_context = {
            "filtered_action": SKIPPED_NAMESPACE,
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
        assert "undefined variables" in msg.lower()
        assert "null" in msg.lower()
        assert "null-safe" in msg.lower()

    def test_sentinel_context_dict_includes_null_namespace_hints(self):
        """Downstream consumers read hints off the error context dict."""
        prompt_context = {
            "filtered_ns": SKIPPED_NAMESPACE,
            "good_ns": {"val": 1},
        }
        raw_prompt = "{{ filtered_ns.some_field }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="consumer",
            )

        assert "null_namespace_hints" in exc_info.value.context

    def test_sentinel_coexisting_with_typo_on_good_ns_no_false_blame(self):
        """A sentinel in scope must not be blamed for a typo on a real namespace."""
        prompt_context = {
            "dep_a": SKIPPED_NAMESPACE,
            "good": {"x": 1},
        }
        raw_prompt = "{{ good.nonexistent_field }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="consumer",
            )

        assert not exc_info.value.null_namespace_hints

    def test_sentinel_field_named_after_its_namespace_still_raises(self):
        """`{{ ns.ns_score }}` on a null namespace raises — it does not render empty.

        Spec 595 strictness change. The removed `_PermissiveNamespace` recovery
        matched `action in str(ue)` against the whole Jinja message, so a field
        name *containing* its namespace name (`observe: [ns.ns_field]`, a common
        convention) made the message contain the namespace name and silently
        rendered the reference empty — while `{{ ns.other_field }}` raised. Same
        null namespace, opposite outcome, decided by field naming. Both raise now.
        """
        prompt_context = {
            "adjacent_architectures": SKIPPED_NAMESPACE,
            "author": {"name": "x"},
        }
        raw_prompt = "{{ adjacent_architectures.adjacent_architectures }}"

        with pytest.raises(TemplateVariableError) as exc_info:
            PromptPreparationService._render_prompt_template(
                raw_prompt,
                prompt_context,
                agent_name="consumer",
            )

        assert "adjacent_architectures" in exc_info.value.null_namespace_hints

    def test_bare_sentinel_reference_renders_empty_not_repr(self):
        """`{{ ns }}` on a null namespace renders "" — never the sentinel's repr.

        The `finalize` callback tested `x is None`, so the sentinel fell through
        and leaked `NullNamespace(reason='skipped')` into the prompt sent to the
        provider. Sibling of the hint gate: same None-vs-sentinel blind spot.
        """
        result = PromptPreparationService._render_prompt_template(
            "[{{ skipped_ns }}]",
            {"skipped_ns": SKIPPED_NAMESPACE, "other": {"x": 1}},
            agent_name="consumer",
        )
        assert result == "[]"

    def test_bare_none_reference_still_renders_empty(self):
        """Parity: the legacy None namespace keeps rendering empty."""
        result = PromptPreparationService._render_prompt_template(
            "[{{ skipped_ns }}]",
            {"skipped_ns": None, "other": {"x": 1}},
            agent_name="consumer",
        )
        assert result == "[]"

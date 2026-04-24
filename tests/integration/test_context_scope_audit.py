"""Comprehensive context_scope audit tests.

Tests every directive (observe, passthrough, drop, seed_path) across:
- RECORD vs FILE granularity
- Wildcard expansion (action.*)
- Version base expansion
- Fan-in (multiple dependencies)
- Framework namespace availability
- Security: drop+passthrough no-leak guarantee
- Edge cases: falsy values, empty lists, null context_scope
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import (
    normalize_all_agent_configs,
    normalize_context_scope,
)
from agent_actions.prompt.context.scope_application import (
    FRAMEWORK_NAMESPACES,
    apply_context_scope,
    format_llm_context,
)
from agent_actions.prompt.context.scope_file_mode import apply_observe_for_file_mode
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.context.scope_parsing import (
    extract_action_names_from_context_scope,
    extract_field_names_from_references,
    parse_field_reference,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fc(**namespaces: dict) -> dict:
    """Build field_context from keyword args."""
    return dict(namespaces)


# ---------------------------------------------------------------------------
# TestObserveDirective
# ---------------------------------------------------------------------------


class TestObserveDirective:
    """Observe fields must appear in llm_context and prompt_context."""

    def test_observe_field_appears_in_llm_context(self):
        field_context = _fc(dep={"summary": "hello", "score": 0.9})
        scope = {"observe": ["dep.summary"]}
        prompt_ctx, llm_ctx, pt = apply_context_scope(field_context, scope, action_name="act")
        assert llm_ctx["dep"]["summary"] == "hello"
        assert "score" not in llm_ctx.get("dep", {})

    def test_observe_field_appears_in_prompt_context(self):
        field_context = _fc(dep={"text": "abc", "extra": "xyz"})
        scope = {"observe": ["dep.text"]}
        prompt_ctx, _, _ = apply_context_scope(field_context, scope, action_name="act")
        assert prompt_ctx["dep"]["text"] == "abc"
        assert "extra" not in prompt_ctx.get("dep", {})

    def test_observe_wildcard_expands_all_fields(self):
        field_context = _fc(dep={"a": 1, "b": 2, "c": 3})
        scope = {"observe": ["dep.*"]}
        _, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        assert llm_ctx["dep"] == {"a": 1, "b": 2, "c": 3}

    def test_observe_multiple_namespaces(self):
        field_context = _fc(dep_a={"x": 10}, dep_b={"y": 20})
        scope = {"observe": ["dep_a.x", "dep_b.y"]}
        _, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        assert llm_ctx["dep_a"]["x"] == 10
        assert llm_ctx["dep_b"]["y"] == 20

    def test_observe_missing_field_raises(self):
        field_context = _fc(dep={"present": "yes"})
        scope = {"observe": ["dep.absent"]}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(field_context, scope, action_name="act")

    def test_observe_preserves_falsy_values(self):
        """0, False, None, '' must all survive observe extraction."""
        field_context = _fc(dep={"zero": 0, "false": False, "none": None, "empty": ""})
        scope = {"observe": ["dep.zero", "dep.false", "dep.none", "dep.empty"]}
        _, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        assert llm_ctx["dep"]["zero"] == 0
        assert llm_ctx["dep"]["false"] is False
        assert llm_ctx["dep"]["none"] is None
        assert llm_ctx["dep"]["empty"] == ""

    def test_observe_version_base_expansion(self):
        """After normalization, version base refs expand to concrete variants."""
        agent_configs = {
            "extract_1": {"is_versioned_agent": True, "version_base_name": "extract"},
            "extract_2": {"is_versioned_agent": True, "version_base_name": "extract"},
            "summarize": {
                "context_scope": {"observe": ["extract.*"]},
                "dependencies": "extract_1",
            },
        }
        normalize_all_agent_configs(agent_configs)
        scope = agent_configs["summarize"]["context_scope"]
        # After normalization, "extract.*" becomes "extract_1.*" and "extract_2.*"
        assert "extract_1.*" in scope["observe"]
        assert "extract_2.*" in scope["observe"]
        assert "extract.*" not in scope["observe"]


# ---------------------------------------------------------------------------
# TestPassthroughDirective
# ---------------------------------------------------------------------------


class TestPassthroughDirective:
    """Passthrough fields must NOT appear in llm_context, but in passthrough output."""

    def test_passthrough_excluded_from_llm_context(self):
        field_context = _fc(dep={"score": 0.8, "text": "hello"})
        scope = {"observe": ["dep.text"], "passthrough": ["dep.score"]}
        _, llm_ctx, pt = apply_context_scope(field_context, scope, action_name="act")
        assert "score" not in llm_ctx.get("dep", {})
        assert pt["dep"]["score"] == 0.8

    def test_passthrough_wildcard(self):
        field_context = _fc(dep={"a": 1, "b": 2})
        scope = {"passthrough": ["dep.*"], "observe": ["dep.*"]}
        _, _, pt = apply_context_scope(field_context, scope, action_name="act")
        assert pt["dep"]["a"] == 1
        assert pt["dep"]["b"] == 2

    def test_passthrough_preserves_falsy_values(self):
        field_context = _fc(dep={"zero": 0, "false": False})
        scope = {"passthrough": ["dep.zero", "dep.false"], "observe": ["dep.zero", "dep.false"]}
        _, _, pt = apply_context_scope(field_context, scope, action_name="act")
        assert pt["dep"]["zero"] == 0
        assert pt["dep"]["false"] is False

    def test_passthrough_in_prompt_context_for_template_rendering(self):
        """Passthrough fields must be in prompt_context so templates can reference them."""
        field_context = _fc(dep={"id": "x123", "text": "hello"})
        scope = {"observe": ["dep.text"], "passthrough": ["dep.id"]}
        prompt_ctx, _, _ = apply_context_scope(field_context, scope, action_name="act")
        assert prompt_ctx["dep"]["id"] == "x123"


# ---------------------------------------------------------------------------
# TestDropDirective
# ---------------------------------------------------------------------------


class TestDropDirective:
    """Dropped fields must not appear in llm_context, passthrough, or prompt_context."""

    def test_drop_removed_from_llm_context(self):
        field_context = _fc(dep={"safe": "ok", "secret": "hidden"})
        scope = {"drop": ["dep.secret"], "observe": ["dep.safe"]}
        _, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        assert "secret" not in llm_ctx.get("dep", {})
        assert llm_ctx["dep"]["safe"] == "ok"

    def test_drop_removed_from_prompt_context(self):
        field_context = _fc(dep={"safe": "ok", "secret": "hidden"})
        scope = {"drop": ["dep.secret"], "observe": ["dep.safe"]}
        prompt_ctx, _, _ = apply_context_scope(field_context, scope, action_name="act")
        assert "secret" not in prompt_ctx.get("dep", {})

    def test_drop_removed_from_passthrough(self):
        """SECURITY: A dropped field must NOT leak via passthrough.

        This was a real bug: passthrough previously read from the original
        field_context (pre-drop) instead of prompt_context (post-drop).
        """
        field_context = _fc(dep={"api_key": "SECRET", "name": "safe"})
        scope = {
            "drop": ["dep.api_key"],
            "observe": ["dep.name"],
            "passthrough": ["dep.api_key"],
        }
        # The dropped field should either raise ConfigurationError
        # (because it's missing from post-drop context) or be absent from passthrough.
        # Either outcome is correct — the key invariant is NO LEAK.
        try:
            _, _, pt = apply_context_scope(field_context, scope, action_name="act")
            # If no error, passthrough must NOT contain the dropped field
            assert "api_key" not in pt.get("dep", {}), (
                "SECURITY: dropped field 'api_key' leaked into passthrough"
            )
        except ConfigurationError:
            # Also acceptable: error because field was dropped before passthrough
            pass

    def test_drop_wildcard_removes_all(self):
        field_context = _fc(dep={"a": 1, "b": 2, "c": 3})
        scope = {"drop": ["dep.*"], "observe": ["dep.*"]}
        prompt_ctx, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        assert prompt_ctx.get("dep", {}) == {}
        assert llm_ctx.get("dep", {}) == {}

    def test_drop_then_observe_specific_raises(self):
        """Observing a field that was dropped must raise, not silently skip."""
        field_context = _fc(dep={"field_a": "value"})
        scope = {"drop": ["dep.field_a"], "observe": ["dep.field_a"]}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(field_context, scope, action_name="act")

    def test_drop_on_nonexistent_field_warns_no_crash(self):
        field_context = _fc(dep={"real": "value"})
        scope = {"drop": ["dep.ghost"]}
        # Should not crash — just warn
        prompt_ctx, _, _ = apply_context_scope(field_context, scope, action_name="act")


# ---------------------------------------------------------------------------
# TestFrameworkNamespaces
# ---------------------------------------------------------------------------


class TestFrameworkNamespaces:
    """Framework namespaces must always be available without being declared in context_scope."""

    def test_version_always_available(self):
        field_context = _fc(
            dep={"text": "hello"},
            version={"i": 1, "idx": 0, "length": 3, "first": True, "last": False},
        )
        scope = {"observe": ["dep.text"]}
        prompt_ctx, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        # Version must be in prompt_context for template rendering
        assert "version" in prompt_ctx
        assert prompt_ctx["version"]["i"] == 1
        # Version must NOT be in llm_context (it's framework, not user data)
        assert "version" not in llm_ctx

    def test_seed_always_available(self):
        field_context = _fc(dep={"text": "hello"})
        scope = {"observe": ["dep.text"]}
        static_data = {"exam_syllabus": "Math 101"}
        prompt_ctx, llm_ctx, _ = apply_context_scope(
            field_context, scope, static_data=static_data, action_name="act"
        )
        assert "seed" in prompt_ctx
        assert prompt_ctx["seed"]["exam_syllabus"] == "Math 101"
        assert "seed" not in llm_ctx

    def test_workflow_always_available(self):
        field_context = _fc(
            dep={"text": "hello"},
            workflow={"name": "test_wf", "project": "proj"},
        )
        scope = {"observe": ["dep.text"]}
        prompt_ctx, _, _ = apply_context_scope(field_context, scope, action_name="act")
        assert "workflow" in prompt_ctx
        assert prompt_ctx["workflow"]["name"] == "test_wf"

    def test_loop_always_available(self):
        field_context = _fc(
            dep={"text": "hello"},
            loop={"index": 0, "length": 5},
        )
        scope = {"observe": ["dep.text"]}
        prompt_ctx, _, _ = apply_context_scope(field_context, scope, action_name="act")
        assert "loop" in prompt_ctx
        assert prompt_ctx["loop"]["index"] == 0

    def test_framework_namespaces_constant_is_correct(self):
        """Sanity check: FRAMEWORK_NAMESPACES includes all expected names."""
        assert FRAMEWORK_NAMESPACES == frozenset({"version", "seed", "workflow", "loop"})

    def test_undeclared_namespace_excluded_from_prompt_context(self):
        """Namespaces not in observe/passthrough/framework must be excluded."""
        field_context = _fc(
            dep={"text": "hello"},
            other={"secret": "should not appear"},
        )
        scope = {"observe": ["dep.text"]}
        prompt_ctx, _, _ = apply_context_scope(field_context, scope, action_name="act")
        assert "other" not in prompt_ctx


# ---------------------------------------------------------------------------
# TestFileModeObserve
# ---------------------------------------------------------------------------


class TestFileModeObserve:
    """FILE mode observe must extract fields from namespaced content."""

    def _make_records(self, ns_name, *contents):
        """Build file-mode records with namespaced content."""
        return [{"content": {ns_name: c}, "source_guid": f"sg_{i}"} for i, c in enumerate(contents)]

    def test_file_mode_enriches_per_record(self):
        """observe specific field -> extracts from namespace, preserves original."""
        data = self._make_records(
            "dep",
            {"question": "What?", "answer": "42", "noise": "junk"},
            {"question": "Why?", "answer": "because", "noise": "more junk"},
        )
        agent_config = {
            "dependencies": "dep",
            "context_scope": {"observe": ["dep.question", "dep.answer"]},
        }
        result = apply_observe_for_file_mode(
            data,
            agent_config,
            agent_name="act",
            agent_indices={"dep": 0, "act": 1},
        )
        assert len(result) == 2
        # Observed fields extracted from namespace
        assert result[0]["content"]["question"] == "What?"
        assert result[0]["content"]["answer"] == "42"
        # Original namespace preserved
        assert result[0]["content"]["dep"]["noise"] == "junk"
        assert result[0]["source_guid"] == "sg_0"
        assert result[1]["content"]["question"] == "Why?"
        assert result[1]["content"]["answer"] == "because"

    def test_file_mode_wildcard_single_ns_includes_all(self):
        """observe: ['dep.*'] extracts all fields from namespace."""
        data = self._make_records(
            "dep",
            {"q": "What?", "a": "42"},
            {"q": "Why?", "a": "because"},
        )
        agent_config = {
            "dependencies": "dep",
            "context_scope": {"observe": ["dep.*"]},
        }
        result = apply_observe_for_file_mode(
            data,
            agent_config,
            agent_name="act",
            agent_indices={"dep": 0, "act": 1},
        )
        assert len(result) == 2
        assert result[0]["content"]["q"] == "What?"
        assert result[0]["content"]["a"] == "42"
        assert result[0]["source_guid"] == "sg_0"
        assert result[1]["content"]["q"] == "Why?"
        assert result[1]["content"]["a"] == "because"

    def test_file_mode_wildcard_does_not_skip_specific_refs(self):
        """observe: ['dep_a.*', 'dep_b.field'] resolves both namespaces."""
        data = [
            {
                "content": {
                    "dep_a": {"text": "hello", "score": 0.9},
                    "dep_b": {"extra": "bonus"},
                },
                "source_guid": "sg_0",
            }
        ]
        agent_config = {
            "dependencies": "dep_a",
            "context_scope": {"observe": ["dep_a.*", "dep_b.extra"]},
        }
        result = apply_observe_for_file_mode(
            data,
            agent_config,
            agent_name="act",
            agent_indices={"dep_a": 0, "dep_b": 1, "act": 2},
        )
        assert len(result) == 1
        # dep_a wildcard extracts all fields (qualified because 2 wildcards? no, only 1)
        assert result[0]["content"]["text"] == "hello"
        assert result[0]["content"]["score"] == 0.9
        # dep_b specific field also extracted
        assert result[0]["content"]["extra"] == "bonus"

    def test_file_mode_no_observe_returns_data_unchanged(self):
        """No observe refs -> data returned as-is."""
        data = [{"content": {"dep": {"a": 1}}, "source_guid": "sg_0"}]
        agent_config = {"dependencies": "dep", "context_scope": {}}
        result = apply_observe_for_file_mode(data, agent_config, agent_name="act")
        assert result == data


# ---------------------------------------------------------------------------
# TestNormalizerVersionExpansion
# ---------------------------------------------------------------------------


class TestNormalizerVersionExpansion:
    """Version base name expansion in normalizer."""

    def test_wildcard_expansion(self):
        version_map = {"extract": ["extract_1", "extract_2", "extract_3"]}
        scope = normalize_context_scope({"observe": ["extract.*"]}, version_map)
        assert scope["observe"] == ["extract_1.*", "extract_2.*", "extract_3.*"]

    def test_specific_field_expansion(self):
        version_map = {"extract": ["extract_1", "extract_2"]}
        scope = normalize_context_scope({"observe": ["extract.score"]}, version_map)
        assert scope["observe"] == ["extract_1.score", "extract_2.score"]

    def test_non_versioned_refs_unchanged(self):
        version_map = {"extract": ["extract_1", "extract_2"]}
        scope = normalize_context_scope({"observe": ["classify.label"]}, version_map)
        assert scope["observe"] == ["classify.label"]

    def test_drop_expansion(self):
        version_map = {"extract": ["extract_1", "extract_2"]}
        scope = normalize_context_scope({"drop": ["extract.raw_html"]}, version_map)
        assert scope["drop"] == ["extract_1.raw_html", "extract_2.raw_html"]

    def test_passthrough_expansion(self):
        version_map = {"extract": ["extract_1", "extract_2"]}
        scope = normalize_context_scope({"passthrough": ["extract.id"]}, version_map)
        assert scope["passthrough"] == ["extract_1.id", "extract_2.id"]

    def test_seed_path_not_expanded(self):
        version_map = {"extract": ["extract_1", "extract_2"]}
        seed = {"syllabus": "data/syllabus.json"}
        scope = normalize_context_scope({"seed_path": seed}, version_map)
        assert scope["seed_path"] == seed

    def test_null_context_scope_returns_empty(self):
        assert normalize_context_scope(None, {}) == {}

    def test_null_list_directive_becomes_empty(self):
        scope = normalize_context_scope({"observe": None}, {})
        assert scope["observe"] == []


# ---------------------------------------------------------------------------
# TestDependencyInference
# ---------------------------------------------------------------------------


class TestDependencyInference:
    """Verify infer_dependencies correctly separates input vs context sources."""

    def test_single_dependency_is_input_source(self):
        config = {
            "dependencies": "dep_a",
            "context_scope": {"observe": ["dep_a.*"]},
        }
        inp, ctx = infer_dependencies(config, ["dep_a", "act"], "act")
        assert inp == ["dep_a"]
        assert ctx == []

    def test_context_scope_adds_context_source(self):
        config = {
            "dependencies": "dep_a",
            "context_scope": {"observe": ["dep_a.*", "dep_b.field"]},
        }
        inp, ctx = infer_dependencies(config, ["dep_a", "dep_b", "act"], "act")
        assert inp == ["dep_a"]
        assert "dep_b" in ctx

    def test_version_base_expansion_in_inference(self):
        config = {
            "dependencies": "extract_1",
            "context_scope": {"observe": ["extract_1.*"]},
        }
        inp, ctx = infer_dependencies(config, ["extract_1", "extract_2", "act"], "act")
        assert "extract_1" in inp

    def test_missing_action_raises(self):
        config = {
            "dependencies": "dep_a",
            "context_scope": {"observe": ["dep_a.*", "ghost.field"]},
        }
        with pytest.raises(ConfigurationError, match="not found in workflow"):
            infer_dependencies(config, ["dep_a", "act"], "act")


# ---------------------------------------------------------------------------
# TestFieldParsing
# ---------------------------------------------------------------------------


class TestFieldParsing:
    """parse_field_reference and extraction utilities."""

    def test_valid_reference(self):
        assert parse_field_reference("action.field") == ("action", "field")

    def test_wildcard_reference(self):
        assert parse_field_reference("action.*") == ("action", "*")

    def test_dotted_field(self):
        assert parse_field_reference("action.nested.path") == ("action", "nested.path")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_field_reference("")

    def test_no_dot_raises(self):
        with pytest.raises(ValueError):
            parse_field_reference("nodot")

    def test_extract_field_names(self):
        refs = ["dep_a.score", "dep_b.label"]
        assert extract_field_names_from_references(refs) == ["score", "label"]

    def test_extract_action_names(self):
        scope = {"observe": ["dep_a.*", "dep_b.field"], "passthrough": ["dep_c.id"]}
        names = extract_action_names_from_context_scope(scope)
        assert names == {"dep_a", "dep_b", "dep_c"}

    def test_extract_action_names_ignores_drop(self):
        """Drop refs should NOT be included — dropped actions don't need loading."""
        scope = {"drop": ["dep_d.secret"], "observe": ["dep_a.text"]}
        names = extract_action_names_from_context_scope(scope)
        assert "dep_d" not in names
        assert "dep_a" in names


# ---------------------------------------------------------------------------
# TestFormatAndMerge
# ---------------------------------------------------------------------------


class TestFormatAndMerge:
    """format_llm_context utility."""

    def test_format_empty_returns_empty(self):
        assert format_llm_context({}) == ""

    def test_format_produces_readable_output(self):
        llm_ctx = {"dep": {"summary": "hello world"}}
        result = format_llm_context(llm_ctx)
        assert "dep.summary" in result
        assert "hello world" in result


# ---------------------------------------------------------------------------
# TestSecurityInvariants
# ---------------------------------------------------------------------------


class TestSecurityInvariants:
    """Security-critical invariants that must never be violated."""

    def test_drop_plus_passthrough_no_leak(self):
        """CRITICAL: If a field is dropped AND passthroughed, drop must win.

        This is the primary security test for the drop+passthrough bug fix.
        """
        field_context = _fc(dep={"api_key": "TOP_SECRET", "name": "safe_data"})
        scope = {
            "drop": ["dep.api_key"],
            "observe": ["dep.name"],
            "passthrough": ["dep.api_key"],
        }
        try:
            _, _, pt = apply_context_scope(field_context, scope, action_name="act")
            # If it doesn't raise, the dropped field MUST be absent
            assert "api_key" not in pt.get("dep", {}), (
                "SECURITY VIOLATION: dropped field leaked via passthrough"
            )
        except ConfigurationError:
            pass  # Also acceptable — field is gone after drop

    def test_drop_wildcard_plus_passthrough_wildcard_no_leak(self):
        """drop: ['dep.*'] + passthrough: ['dep.*'] -> nothing leaks."""
        field_context = _fc(dep={"key": "secret", "data": "also_secret"})
        scope = {
            "drop": ["dep.*"],
            "observe": ["dep.*"],
            "passthrough": ["dep.*"],
        }
        prompt_ctx, llm_ctx, pt = apply_context_scope(field_context, scope, action_name="act")
        # Everything dropped: nothing in any output
        assert prompt_ctx.get("dep", {}) == {}
        assert llm_ctx.get("dep", {}) == {}
        assert pt.get("dep", {}) == {} or pt.get("dep") is None

    def test_undeclared_fields_never_in_llm_context(self):
        """Fields not in observe must NEVER appear in llm_context."""
        field_context = _fc(
            dep={"declared": "yes", "undeclared": "no"},
            other={"leak": "should not appear"},
        )
        scope = {"observe": ["dep.declared"]}
        _, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        assert "undeclared" not in llm_ctx.get("dep", {})
        assert "other" not in llm_ctx

    def test_source_namespace_excluded_when_not_declared(self):
        """'source' namespace must be excluded from prompt_context if not declared."""
        field_context = _fc(
            source={"input_text": "raw data"},
            dep={"text": "processed"},
        )
        scope = {"observe": ["dep.text"]}
        prompt_ctx, _, _ = apply_context_scope(field_context, scope, action_name="act")
        assert "source" not in prompt_ctx


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_observe_list(self):
        field_context = _fc(dep={"text": "hello"})
        scope = {"observe": []}
        prompt_ctx, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        assert llm_ctx == {}

    def test_empty_field_context(self):
        scope = {"observe": ["dep.*"]}
        _, llm_ctx, _ = apply_context_scope({}, scope, action_name="act")
        assert llm_ctx == {}

    def test_nested_field_extraction(self):
        """observe with dot-path nested field."""
        field_context = _fc(dep={"stats": {"mean": 0.5, "std": 0.1}})
        scope = {"observe": ["dep.stats"]}
        _, llm_ctx, _ = apply_context_scope(field_context, scope, action_name="act")
        assert llm_ctx["dep"]["stats"] == {"mean": 0.5, "std": 0.1}

    def test_multiple_directives_combined(self):
        """observe + passthrough + drop on different fields of same namespace."""
        field_context = _fc(dep={"visible": "see", "passthru": "forward", "secret": "hide"})
        scope = {
            "observe": ["dep.visible"],
            "passthrough": ["dep.passthru"],
            "drop": ["dep.secret"],
        }
        prompt_ctx, llm_ctx, pt = apply_context_scope(field_context, scope, action_name="act")
        assert llm_ctx["dep"]["visible"] == "see"
        assert pt["dep"]["passthru"] == "forward"
        assert "secret" not in llm_ctx.get("dep", {})
        assert "secret" not in pt.get("dep", {})
        assert "secret" not in prompt_ctx.get("dep", {})

    def test_seed_data_injected_under_seed_namespace(self):
        field_context = _fc(dep={"text": "hello"})
        scope = {"observe": ["dep.text"]}
        static_data = {"ref_data": [1, 2, 3]}
        prompt_ctx, _, _ = apply_context_scope(
            field_context, scope, static_data=static_data, action_name="act"
        )
        assert prompt_ctx["seed"]["ref_data"] == [1, 2, 3]

    def test_orphaned_directives_detected(self):
        """context_scope: null with observe as sibling -> error."""
        from agent_actions.input.context.normalizer import detect_orphaned_directives

        config = {"context_scope": None, "observe": ["dep.*"]}
        orphaned = detect_orphaned_directives(config)
        assert "observe" in orphaned

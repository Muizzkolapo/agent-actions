"""Tests for error class construction and base class delegation."""

from agent_actions.errors.operations import TemplateVariableError
from agent_actions.errors.preflight import ContextStructureError


class TestTemplateVariableError:
    """Verify TemplateVariableError delegates context and cause to base class."""

    def test_context_propagated_to_base(self):
        cause = ValueError("original")
        err = TemplateVariableError(
            missing_variables=["foo", "bar"],
            available_variables=["baz"],
            agent_name="test_agent",
            mode="batch",
            cause=cause,
        )
        assert err.context["agent_name"] == "test_agent"
        assert err.context["mode"] == "batch"
        assert err.context["missing_variables"] == ["foo", "bar"]
        assert err.context["available_variables"] == ["baz"]

    def test_cause_chained_via_base(self):
        cause = ValueError("original")
        err = TemplateVariableError(
            missing_variables=["x"],
            available_variables=[],
            agent_name="a",
            mode="online",
            cause=cause,
        )
        assert err.cause is cause

    def test_namespace_context_and_template_line_in_context(self):
        err = TemplateVariableError(
            missing_variables=["v"],
            available_variables=["w"],
            agent_name="a",
            mode="batch",
            cause=ValueError("e"),
            namespace_context={"ns": ["f1"]},
            template_line=42,
        )
        assert err.context["namespace_context"] == {"ns": ["f1"]}
        assert err.context["template_line"] == 42


class TestContextStructureError:
    """Verify ContextStructureError reports only truly missing fields."""

    def test_partial_missing_reports_only_absent_fields(self):
        err = ContextStructureError(
            "partial",
            expected_fields=["a", "b"],
            actual_fields=["a"],
        )
        assert err.missing_references == ["b"]
        assert "a" not in err.missing_references

    def test_all_missing(self):
        err = ContextStructureError(
            "all gone",
            expected_fields=["a", "b"],
            actual_fields=[],
        )
        assert sorted(err.missing_references) == ["a", "b"]

    def test_none_missing(self):
        err = ContextStructureError(
            "fine",
            expected_fields=["a"],
            actual_fields=["a", "b"],
        )
        assert err.missing_references == []

    def test_actual_fields_none_treats_all_as_missing(self):
        err = ContextStructureError(
            "unknown",
            expected_fields=["x", "y"],
        )
        assert err.missing_references == ["x", "y"]

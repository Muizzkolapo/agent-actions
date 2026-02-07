"""Tests for error class construction and base class delegation."""

import pytest

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

    @pytest.mark.parametrize(
        "expected,actual,missing",
        [
            pytest.param(["a", "b"], ["a"], ["b"], id="partial_missing"),
            pytest.param(["a", "b"], [], ["a", "b"], id="all_missing"),
            pytest.param(["a"], ["a", "b"], [], id="none_missing"),
        ],
    )
    def test_missing_references(self, expected, actual, missing):
        err = ContextStructureError("msg", expected_fields=expected, actual_fields=actual)
        assert sorted(err.missing_references) == sorted(missing)

    def test_actual_fields_none_treats_all_as_missing(self):
        err = ContextStructureError("unknown", expected_fields=["x", "y"])
        assert err.missing_references == ["x", "y"]

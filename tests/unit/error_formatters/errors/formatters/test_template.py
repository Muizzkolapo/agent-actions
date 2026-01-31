"""Tests for TemplateErrorFormatter with enhanced namespace context."""

from agent_actions.errors.operations import TemplateVariableError
from agent_actions.logging.errors.formatters.template import TemplateErrorFormatter


class TestTemplateErrorFormatter:
    """Tests for TemplateErrorFormatter."""

    def test_can_handle_template_variable_error(self):
        """Verify can_handle detects TemplateVariableError."""
        formatter = TemplateErrorFormatter()
        exc = TemplateVariableError(
            missing_variables=["classify.question_type"],
            available_variables=["source.content"],
            agent_name="test_agent",
            mode="batch",
            cause=Exception("original error"),
        )
        assert formatter.can_handle(exc, exc, str(exc)) is True

    def test_can_handle_rejects_other_exceptions(self):
        """Verify can_handle returns False for non-template errors."""
        formatter = TemplateErrorFormatter()
        exc = ValueError("some error")
        assert formatter.can_handle(exc, exc, str(exc)) is False

    def test_namespace_context_in_error_message(self):
        """Test that namespace context is displayed in error message."""
        formatter = TemplateErrorFormatter()

        exc = TemplateVariableError(
            missing_variables=["classify.question_type"],
            available_variables=["classify.question_category", "classify.difficulty_level"],
            agent_name="write_question",
            mode="batch",
            cause=Exception("'dict object' has no attribute 'question_type'"),
            namespace_context={
                "source": ["page_content", "title"],
                "classify": ["question_category", "difficulty_level", "tags"],
            },
        )

        context = {
            "agent_name": "write_question",
            "missing_variables": ["classify.question_type"],
            "available_variables": ["classify.question_category", "classify.difficulty_level"],
            "mode": "batch",
        }

        result = formatter.format(exc, exc, str(exc), context)

        # Verify namespace breakdown is present
        assert "Reference: classify.question_type" in result.details
        assert "Namespace 'classify' exists: YES" in result.details
        assert "Field 'question_type' in namespace: NO" in result.details
        assert "Available in 'classify':" in result.details
        assert "question_category" in result.details

    def test_suggestion_for_similar_field(self):
        """Test that similar field suggestions are provided."""
        formatter = TemplateErrorFormatter()

        exc = TemplateVariableError(
            missing_variables=["classify.question_type"],
            available_variables=["classify.question_category"],
            agent_name="write_question",
            mode="batch",
            cause=Exception("'dict object' has no attribute 'question_type'"),
            namespace_context={
                "classify": ["question_category", "difficulty_level", "tags"],
            },
        )

        context = {
            "agent_name": "write_question",
            "missing_variables": ["classify.question_type"],
        }

        result = formatter.format(exc, exc, str(exc), context)

        # Should suggest similar field
        assert "Did you mean 'classify.question_category'?" in result.details

    def test_missing_namespace_shows_available_namespaces(self):
        """Test that missing namespace shows available namespaces."""
        formatter = TemplateErrorFormatter()

        exc = TemplateVariableError(
            missing_variables=["unknown_action.field"],
            available_variables=["source.content", "classify.result"],
            agent_name="test_agent",
            mode="batch",
            cause=Exception("'unknown_action' is undefined"),
            namespace_context={
                "source": ["content", "title"],
                "classify": ["result", "confidence"],
            },
        )

        context = {
            "agent_name": "test_agent",
            "missing_variables": ["unknown_action.field"],
        }

        result = formatter.format(exc, exc, str(exc), context)

        assert "Namespace 'unknown_action' exists: NO" in result.details
        assert "Available namespaces:" in result.details
        assert "source" in result.details
        assert "classify" in result.details

    def test_top_level_variable_missing(self):
        """Test handling of top-level variable without namespace."""
        formatter = TemplateErrorFormatter()

        exc = TemplateVariableError(
            missing_variables=["undefined_var"],
            available_variables=["source.content"],
            agent_name="test_agent",
            mode="batch",
            cause=Exception("'undefined_var' is undefined"),
            namespace_context={
                "source": ["content", "title"],
            },
        )

        context = {
            "agent_name": "test_agent",
            "missing_variables": ["undefined_var"],
        }

        result = formatter.format(exc, exc, str(exc), context)

        assert "Missing variable: 'undefined_var'" in result.details
        assert "Available namespaces:" in result.details

    def test_hint_for_missing_namespace(self):
        """Test that hint suggests adding namespace to dependencies."""
        formatter = TemplateErrorFormatter()

        exc = TemplateVariableError(
            missing_variables=["missing_action.field"],
            available_variables=[],
            agent_name="test_agent",
            mode="batch",
            cause=Exception("error"),
            namespace_context={
                "source": ["content"],
            },
        )

        context = {
            "agent_name": "test_agent",
            "missing_variables": ["missing_action.field"],
        }

        result = formatter.format(exc, exc, str(exc), context)

        assert "Add 'missing_action' to dependencies" in result.fix

    def test_hint_for_existing_namespace_missing_field(self):
        """Test that hint suggests checking field production."""
        formatter = TemplateErrorFormatter()

        exc = TemplateVariableError(
            missing_variables=["classify.missing_field"],
            available_variables=["classify.result"],
            agent_name="test_agent",
            mode="batch",
            cause=Exception("error"),
            namespace_context={
                "classify": ["result"],
            },
        )

        context = {
            "agent_name": "test_agent",
            "missing_variables": ["classify.missing_field"],
        }

        result = formatter.format(exc, exc, str(exc), context)

        assert "Check that 'classify' produces the referenced field" in result.fix

    def test_many_fields_truncated(self):
        """Test that more than 10 fields are truncated."""
        formatter = TemplateErrorFormatter()

        many_fields = [f"field_{i}" for i in range(15)]
        exc = TemplateVariableError(
            missing_variables=["ns.missing"],
            available_variables=[f"ns.{f}" for f in many_fields],
            agent_name="test_agent",
            mode="batch",
            cause=Exception("error"),
            namespace_context={
                "ns": many_fields,
            },
        )

        context = {
            "agent_name": "test_agent",
            "missing_variables": ["ns.missing"],
        }

        result = formatter.format(exc, exc, str(exc), context)

        assert "(and 5 more)" in result.details

    def test_empty_missing_variables(self):
        """Test handling when missing variables list is empty."""
        formatter = TemplateErrorFormatter()

        exc = TemplateVariableError(
            missing_variables=[],
            available_variables=["source.content"],
            agent_name="test_agent",
            mode="batch",
            cause=Exception("some template error"),
            namespace_context={
                "source": ["content"],
            },
        )

        context = {
            "agent_name": "test_agent",
            "missing_variables": [],
        }

        result = formatter.format(exc, exc, str(exc), context)

        assert "Unable to parse missing variable from error" in result.details
        assert result.fix == "Check template syntax."

    def test_no_namespace_context(self):
        """Test handling when namespace_context is not provided."""
        formatter = TemplateErrorFormatter()

        exc = TemplateVariableError(
            missing_variables=["classify.field"],
            available_variables=["source.content"],
            agent_name="test_agent",
            mode="batch",
            cause=Exception("error"),
            # No namespace_context provided
        )

        context = {
            "agent_name": "test_agent",
            "missing_variables": ["classify.field"],
        }

        result = formatter.format(exc, exc, str(exc), context)

        # Should still produce valid output
        assert "Template rendering failed" in result.details
        assert "Reference: classify.field" in result.details
        assert "Namespace 'classify' exists: NO" in result.details


class TestFindSimilar:
    """Tests for the _find_similar helper method."""

    def test_finds_similar_field(self):
        """Test that similar fields are found."""
        formatter = TemplateErrorFormatter()
        result = formatter._find_similar("question_type", ["question_category", "tags"])
        assert result == "question_category"

    def test_no_match_below_threshold(self):
        """Test that no match is returned if below threshold."""
        formatter = TemplateErrorFormatter()
        result = formatter._find_similar("xyz", ["abc", "def"])
        assert result is None

    def test_case_insensitive_matching(self):
        """Test that matching is case insensitive."""
        formatter = TemplateErrorFormatter()
        result = formatter._find_similar("QUESTION_TYPE", ["question_category", "tags"])
        assert result == "question_category"

    def test_empty_candidates(self):
        """Test handling of empty candidates list."""
        formatter = TemplateErrorFormatter()
        result = formatter._find_similar("field", [])
        assert result is None

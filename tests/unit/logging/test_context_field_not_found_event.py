"""Tests for ContextFieldNotFoundEvent message formatting."""

from agent_actions.logging.events.io_events import ContextFieldNotFoundEvent


class TestContextFieldNotFoundEvent:
    """Verify message branching on empty vs non-empty namespace."""

    def test_empty_namespace_produces_namespace_message(self):
        """When namespace is empty, message should say 'Namespace X not found'."""
        event = ContextFieldNotFoundEvent(
            action_name="write_question",
            field_ref="classify",
            namespace="",
            available_fields=["source", "version", "seed"],
        )

        assert "Namespace 'classify' not found in context" in event.message
        assert "Available namespaces: source, version, seed" in event.message
        assert "context_scope.observe" in event.message

    def test_nonempty_namespace_produces_field_message(self):
        """When namespace is present, message should say 'Field X not found in Y'."""
        event = ContextFieldNotFoundEvent(
            action_name="write_question",
            field_ref="question_type",
            namespace="classify",
            available_fields=["question_category", "difficulty_level"],
        )

        assert "Field 'question_type' not found in 'classify'" in event.message
        assert "Available: question_category, difficulty_level" in event.message
        assert "context_scope.observe" not in event.message

    def test_available_fields_truncated_at_five(self):
        """More than 5 available fields should be truncated."""
        event = ContextFieldNotFoundEvent(
            action_name="test",
            field_ref="missing",
            namespace="ns",
            available_fields=["a", "b", "c", "d", "e", "f", "g"],
        )

        assert "(+2 more)" in event.message

    def test_empty_available_fields(self):
        """Empty available_fields should not crash."""
        event = ContextFieldNotFoundEvent(
            action_name="test",
            field_ref="missing",
            namespace="",
            available_fields=[],
        )

        assert "Namespace 'missing' not found in context" in event.message
        assert "Available namespaces: ." in event.message

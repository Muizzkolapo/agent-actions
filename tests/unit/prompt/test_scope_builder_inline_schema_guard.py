"""Tests for the InlineSchema corruption guard in DependencyNamespaceBuilder.

When a corrupted namespace contains a compiled JSON Schema definition
(``{"title": "InlineSchema", ...}``) instead of actual action output,
the guard wraps it as ``SKIPPED_NAMESPACE`` to prevent RecordContextError
crashes in downstream actions.
"""

from agent_actions.prompt.context.null_namespace import is_null_namespace
from agent_actions.prompt.context.scope_builder import build_field_context_with_history


def _make_current_item(content: dict) -> dict:
    return {
        "content": content,
        "lineage": ["node-1"],
        "source_guid": "sg-1",
    }


INLINE_SCHEMA_CORRUPTION = {
    "title": "InlineSchema",
    "type": "object",
    "properties": {"distractor_explanation_1": {"type": "string"}},
    "required": [],
    "additionalProperties": False,
}

PARTIAL_CORRUPTION = {
    "title": "InlineSchema",
    "type": "object",
    "properties": {"optimal_code": {"type": "string"}},
    "required": ["optimal_code"],
    "additionalProperties": False,
}

VALID_NAMESPACE = {"distractor_explanation_1": "The answer is wrong because..."}


class TestInlineSchemaGuard:
    """Corrupted InlineSchema namespaces are wrapped as SKIPPED_NAMESPACE."""

    def test_full_corruption_skipped(self):
        """Full InlineSchema corruption → SKIPPED_NAMESPACE."""
        current_item = _make_current_item({"generate_quiz": INLINE_SCHEMA_CORRUPTION})
        agent_config = {
            "dependencies": ["generate_quiz"],
            "context_scope": {"observe": ["generate_quiz.distractor_explanation_1"]},
        }

        result = build_field_context_with_history(
            agent_name="review",
            agent_config=agent_config,
            agent_indices={"generate_quiz": 0, "review": 1},
            current_item=current_item,
            context_scope=agent_config["context_scope"],
        )

        assert is_null_namespace(result["generate_quiz"])

    def test_partial_corruption_skipped(self):
        """InlineSchema with different fields → SKIPPED_NAMESPACE."""
        current_item = _make_current_item({"generate_quiz": PARTIAL_CORRUPTION})
        agent_config = {
            "dependencies": ["generate_quiz"],
            "context_scope": {"observe": ["generate_quiz.optimal_code"]},
        }

        result = build_field_context_with_history(
            agent_name="review",
            agent_config=agent_config,
            agent_indices={"generate_quiz": 0, "review": 1},
            current_item=current_item,
            context_scope=agent_config["context_scope"],
        )

        assert is_null_namespace(result["generate_quiz"])

    def test_valid_namespace_not_affected(self):
        """Normal action output flows through without triggering the guard."""
        current_item = _make_current_item({"generate_quiz": VALID_NAMESPACE})
        agent_config = {
            "dependencies": ["generate_quiz"],
            "context_scope": {"observe": ["generate_quiz.distractor_explanation_1"]},
        }

        result = build_field_context_with_history(
            agent_name="review",
            agent_config=agent_config,
            agent_indices={"generate_quiz": 0, "review": 1},
            current_item=current_item,
            context_scope=agent_config["context_scope"],
        )

        assert not is_null_namespace(result["generate_quiz"])
        assert result["generate_quiz"] == {
            "distractor_explanation_1": "The answer is wrong because..."
        }

    def test_user_data_with_title_not_affected(self):
        """Real user data that has 'title' field is not falsely detected."""
        user_data = {"title": "My Document", "body": "Some text"}
        current_item = _make_current_item({"extract": user_data})
        agent_config = {
            "dependencies": ["extract"],
            "context_scope": {"observe": ["extract.title", "extract.body"]},
        }

        result = build_field_context_with_history(
            agent_name="summarize",
            agent_config=agent_config,
            agent_indices={"extract": 0, "summarize": 1},
            current_item=current_item,
            context_scope=agent_config["context_scope"],
        )

        assert not is_null_namespace(result["extract"])
        assert result["extract"] == {"title": "My Document", "body": "Some text"}

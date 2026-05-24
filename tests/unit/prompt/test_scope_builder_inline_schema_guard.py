"""Tests for the zero-overlap corruption guard in DependencyNamespaceBuilder.

When a namespace has zero overlap with declared observe fields (e.g. a
compiled JSON Schema stored as action content, or any other form of
content corruption), the guard wraps it as ``SKIPPED_NAMESPACE`` to
prevent RecordContextError crashes in downstream actions.
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

# Named schema corruption — NOT title == "InlineSchema"
NAMED_SCHEMA_CORRUPTION = {
    "title": "QuizOutputSchema",
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}

# Arbitrary garbage namespace — no schema keys at all
GARBAGE_NAMESPACE = {"foo": 1, "bar": 2, "baz": 3}

VALID_NAMESPACE = {"distractor_explanation_1": "The answer is wrong because..."}


class TestZeroOverlapGuard:
    """Namespaces with zero overlap with declared fields are wrapped as SKIPPED_NAMESPACE."""

    def test_inline_schema_corruption_skipped(self):
        """InlineSchema echo has zero overlap with declared fields → SKIPPED."""
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

    def test_named_schema_corruption_skipped(self):
        """Named schema corruption (not InlineSchema) also caught by zero-overlap."""
        current_item = _make_current_item({"generate_quiz": NAMED_SCHEMA_CORRUPTION})
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

    def test_garbage_namespace_skipped(self):
        """Arbitrary garbage with zero field overlap → SKIPPED."""
        current_item = _make_current_item({"generate_quiz": GARBAGE_NAMESPACE})
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

    def test_valid_namespace_not_affected(self):
        """Normal action output has overlap with declared fields → flows through."""
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

    def test_user_data_with_matching_fields(self):
        """User data with fields matching observe spec → not affected."""
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

    def test_wildcard_observe_bypasses_guard(self):
        """Wildcard observe (action.*) sets allowed_fields=None → guard skipped."""
        current_item = _make_current_item({"generate_quiz": INLINE_SCHEMA_CORRUPTION})
        agent_config = {
            "dependencies": ["generate_quiz"],
            "context_scope": {"observe": ["generate_quiz.*"]},
        }

        result = build_field_context_with_history(
            agent_name="review",
            agent_config=agent_config,
            agent_indices={"generate_quiz": 0, "review": 1},
            current_item=current_item,
            context_scope=agent_config["context_scope"],
        )

        # Wildcard → allowed_fields is None → guard doesn't fire → all keys loaded
        assert not is_null_namespace(result["generate_quiz"])

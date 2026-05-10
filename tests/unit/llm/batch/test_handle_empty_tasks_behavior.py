"""Tests for _handle_empty_tasks where-clause behavior enum path."""

from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.services.submission import BatchSubmissionService


def _make_service() -> BatchSubmissionService:
    return BatchSubmissionService(
        task_preparator=MagicMock(),
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        registry_manager_factory=MagicMock(),
    )


class TestHandleEmptyTasksWhereBehavior:
    """Test that _handle_empty_tasks uses WhereClauseBehavior enum correctly."""

    def test_filter_behavior_returns_tombstone(self):
        """where_clause behavior='filter' produces a tombstone passthrough."""
        service = _make_service()
        agent_config = {"where_clause": {"behavior": "filter"}}
        context_map = {"row1": {"data": "val"}}

        result = service._handle_empty_tasks(
            agent_config=agent_config,
            context_map=context_map,
            data=[{"id": 1}],
            output_directory="/tmp/out",
        )

        assert result.passthrough["type"] == "tombstone"
        assert result.passthrough["data"] == []

    def test_skip_behavior_returns_passthrough_from_context(self):
        """where_clause behavior='skip' produces passthrough built from context map, not empty tombstone."""
        service = _make_service()
        agent_config = {"where_clause": {"behavior": "skip"}}
        context_map = {"row1": {"data": "val"}}

        result = service._handle_empty_tasks(
            agent_config=agent_config,
            context_map=context_map,
            data=[{"id": 1}],
            output_directory="/tmp/out",
        )

        assert result.passthrough is not None
        # Skip path uses BatchPassthroughBuilder.from_context (processes skipped rows),
        # filter path returns a bare tombstone with data=[].
        # Both have type="tombstone" but the skip path goes through the builder.
        assert result.passthrough["output_directory"] == "/tmp/out"

    def test_default_behavior_is_filter(self):
        """Missing behavior key defaults to 'filter' (tombstone)."""
        service = _make_service()
        agent_config = {"where_clause": {}}
        context_map = {"row1": {"data": "val"}}

        result = service._handle_empty_tasks(
            agent_config=agent_config,
            context_map=context_map,
            data=[{"id": 1}],
            output_directory="/tmp/out",
        )

        assert result.passthrough["type"] == "tombstone"

    def test_invalid_behavior_raises_value_error(self):
        """Unknown behavior value raises ValueError from WhereClauseBehavior constructor."""
        service = _make_service()
        agent_config = {"where_clause": {"behavior": "explode"}}

        with pytest.raises(ValueError, match="'explode' is not a valid"):
            service._handle_empty_tasks(
                agent_config=agent_config,
                context_map={},
                data=[],
                output_directory="/tmp/out",
            )

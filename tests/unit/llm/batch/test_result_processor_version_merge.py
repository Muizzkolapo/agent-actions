"""Tests for version_merge branching in batch result strategy.

kind:llm with version_consumption must wrap output under action_name namespace.
kind:tool with version_consumption flat-spreads into existing content.

The guard at record_helpers.py ensures only TOOL actions get flat spread.
If someone removes the `and is_tool` guard, LLM actions would silently corrupt
the content namespace structure.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult


def _make_ctx(
    agent_config: dict[str, Any],
    custom_id: str,
    original_row: dict[str, Any],
) -> BatchProcessingContext:
    """Build a BatchProcessingContext with reconciler for version_merge testing."""
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={custom_id: original_row},
        output_directory="/tmp/output",
        agent_config=agent_config,
    )
    ctx.reconciler = BatchResultReconciler(context_map={custom_id: original_row})
    return ctx


@pytest.fixture
def processor():
    """BatchResultStrategy with enrichment pipeline stubbed to pass through."""
    p = BatchResultStrategy()
    p._enrichment_pipeline = MagicMock()
    p._enrichment_pipeline.enrich.side_effect = lambda result, context: result
    return p


class TestLLMVersionMergeWrapsUnderActionName:
    """kind:llm with version_consumption must wrap output under action_name, NOT flat spread."""

    def test_llm_version_merge_wraps_under_action_name(self, processor):
        """LLM action with version_consumption_config wraps output under namespace."""
        custom_id = "rec_001"
        original_row = {
            "source_guid": "src_001",
            "content": {
                "source": {"url": "http://example.com"},
                "voter_1": {"vote": "keep"},
            },
        }
        agent_config = {
            "action_name": "aggregate",
            "kind": "llm",
            "version_consumption_config": {"source": "voter_1", "pattern": "merge"},
        }
        ctx = _make_ctx(agent_config, custom_id, original_row)
        batch_result = BatchResult(
            custom_id=custom_id,
            content={"decision": "keep", "reason": "majority vote"},
            success=True,
        )

        result = processor._process_successful_result(ctx, batch_result, custom_id)

        assert len(result.data) == 1
        content = result.data[0]["content"]
        assert content["aggregate"] == {"decision": "keep", "reason": "majority vote"}
        assert content["source"] == {"url": "http://example.com"}
        assert content["voter_1"] == {"vote": "keep"}
        assert "decision" not in content
        assert "reason" not in content


class TestToolVersionMergeFlatSpreads:
    """kind:tool with version_consumption DOES flat spread (existing behavior)."""

    def test_tool_version_merge_flat_spreads(self, processor):
        """Tool action with version_consumption_config flat-spreads into content."""
        custom_id = "rec_001"
        original_row = {
            "source_guid": "src_001",
            "content": {
                "source": {"url": "http://example.com"},
                "voter_1": {"vote": "keep"},
                "voter_2": {"vote": "reject"},
            },
        }
        agent_config = {
            "action_name": "aggregate_votes",
            "kind": "tool",
            "version_consumption_config": {"source": "voter_1", "pattern": "merge"},
        }
        ctx = _make_ctx(agent_config, custom_id, original_row)
        batch_result = BatchResult(
            custom_id=custom_id,
            content={"final_decision": "keep", "confidence": 0.8},
            success=True,
        )

        result = processor._process_successful_result(ctx, batch_result, custom_id)

        assert len(result.data) == 1
        content = result.data[0]["content"]
        assert content["final_decision"] == "keep"
        assert content["confidence"] == 0.8
        assert content["source"] == {"url": "http://example.com"}
        assert content["voter_1"] == {"vote": "keep"}
        assert "aggregate_votes" not in content


class TestNoVersionMergeWrapsNormally:
    """Actions without version_consumption_config always wrap under action_name."""

    def test_llm_no_version_merge_wraps(self, processor):
        """LLM action without version_consumption wraps under action_name."""
        custom_id = "rec_001"
        original_row = {
            "source_guid": "src_001",
            "content": {"source": {"url": "http://example.com"}},
        }
        agent_config = {
            "action_name": "classify",
            "kind": "llm",
        }
        ctx = _make_ctx(agent_config, custom_id, original_row)
        batch_result = BatchResult(
            custom_id=custom_id,
            content={"category": "tech"},
            success=True,
        )

        result = processor._process_successful_result(ctx, batch_result, custom_id)

        content = result.data[0]["content"]
        assert content["classify"] == {"category": "tech"}
        assert content["source"] == {"url": "http://example.com"}
        assert "category" not in content

    def test_tool_no_version_merge_wraps(self, processor):
        """Tool action without version_consumption wraps under action_name."""
        custom_id = "rec_001"
        original_row = {
            "source_guid": "src_001",
            "content": {"source": {"url": "http://example.com"}},
        }
        agent_config = {
            "action_name": "extract",
            "kind": "tool",
        }
        ctx = _make_ctx(agent_config, custom_id, original_row)
        batch_result = BatchResult(
            custom_id=custom_id,
            content={"entities": ["AI", "ML"]},
            success=True,
        )

        result = processor._process_successful_result(ctx, batch_result, custom_id)

        content = result.data[0]["content"]
        assert content["extract"] == {"entities": ["AI", "ML"]}
        assert "entities" not in content

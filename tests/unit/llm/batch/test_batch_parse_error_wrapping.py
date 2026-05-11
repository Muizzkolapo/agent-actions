"""Tests for _parse_error wrapping when batch result content is unparsed string.

When json_mode=True and the LLM response fails all parse strategies,
batch_result_strategy must wrap the string in a _parse_error dict so
the batch reprompt loop (EvaluationLoop) can detect and retry.
"""

from typing import Any

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
    json_mode: bool = True,
) -> BatchProcessingContext:
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={custom_id: original_row},
        output_directory="/tmp/output",
        agent_config=agent_config,
        json_mode=json_mode,
    )
    ctx.reconciler = BatchResultReconciler(context_map={custom_id: original_row})
    return ctx


@pytest.fixture
def processor():
    return BatchResultStrategy()


class TestJsonModeParseErrorWrapping:
    """String content in json_mode must produce _parse_error for reprompt."""

    def test_string_content_in_json_mode_produces_parse_error(self, processor):
        """Unparsed string in json_mode wraps as _parse_error dict."""
        custom_id = "rec_001"
        original_row = {"source_guid": "src_001", "content": {}}
        agent_config = {"action_name": "my_action"}
        ctx = _make_ctx(agent_config, custom_id, original_row, json_mode=True)

        # Simulate a batch result where content stayed as raw string
        # (all parse strategies in _parse_json_content failed)
        batch_result = BatchResult(
            custom_id=custom_id,
            content="```json\nthis is not valid json\n```",
            success=True,
        )

        result = processor._process_successful_result(ctx, batch_result, custom_id)

        assert len(result.data) == 1
        content = result.data[0]["content"]
        action_ns = content["my_action"]
        assert "_parse_error" in action_ns
        assert "raw_response" in action_ns

    def test_string_content_in_non_json_mode_uses_output_field(self, processor):
        """Plain text in non-json mode wraps in output_field, not _parse_error."""
        custom_id = "rec_001"
        original_row = {"source_guid": "src_001", "content": {}}
        agent_config = {"action_name": "my_action"}
        ctx = _make_ctx(agent_config, custom_id, original_row, json_mode=False)

        batch_result = BatchResult(
            custom_id=custom_id,
            content="Hello world",
            success=True,
        )

        result = processor._process_successful_result(ctx, batch_result, custom_id)

        assert len(result.data) == 1
        content = result.data[0]["content"]
        action_ns = content["my_action"]
        assert "_parse_error" not in action_ns
        assert action_ns.get("raw_response") == "Hello world"

    def test_dict_content_in_json_mode_not_wrapped(self, processor):
        """Successfully parsed dict content is NOT wrapped as _parse_error."""
        custom_id = "rec_001"
        original_row = {"source_guid": "src_001", "content": {}}
        agent_config = {"action_name": "my_action"}
        ctx = _make_ctx(agent_config, custom_id, original_row, json_mode=True)

        batch_result = BatchResult(
            custom_id=custom_id,
            content={"question": "What?", "answer": "Yes"},
            success=True,
        )

        result = processor._process_successful_result(ctx, batch_result, custom_id)

        assert len(result.data) == 1
        content = result.data[0]["content"]
        action_ns = content["my_action"]
        assert action_ns == {"question": "What?", "answer": "Yes"}
        assert "_parse_error" not in action_ns

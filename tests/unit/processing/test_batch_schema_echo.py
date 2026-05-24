"""Tests for schema-echo detection in batch result strategy.

Verifies that ``BatchResultStrategy._process_successful_result`` replaces
schema-echo content with ``_parse_error`` dicts before structuring records.
"""

from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchResultStrategy,
)
from agent_actions.llm.providers.batch_base import BatchResult

SCHEMA_ECHO = {
    "title": "InlineSchema",
    "type": "object",
    "properties": {"distractor_explanation_1": {"type": "string"}},
    "required": [],
    "additionalProperties": False,
}

VALID_OUTPUT = {"distractor_explanation_1": "The earth is not flat because..."}


def _make_agent_config(action_name="generate_quiz"):
    return {
        "action_name": action_name,
        "agent_type": action_name,
        "json_mode": True,
        "output_field": "raw_response",
        "dependencies": ["extract"],
    }


def _make_context_map(custom_id, row):
    """Build a minimal context map entry for reconciliation."""
    return {custom_id: row}


def _make_original_row(custom_id):
    return {
        "target_id": custom_id,
        "source_guid": "sg-001",
        "content": {"extract": {"text": "hello"}},
        "lineage": ["node-1"],
    }


class TestBatchSchemaEchoDetection:
    """Schema-echo in batch result content is replaced with _parse_error."""

    def test_schema_echo_replaced(self):
        """Full schema echo in batch result → _parse_error in output record."""
        custom_id = "tid-001"
        original_row = _make_original_row(custom_id)
        context_map = _make_context_map(custom_id, original_row)
        agent_config = _make_agent_config()

        batch_result = BatchResult(
            custom_id=custom_id,
            content=SCHEMA_ECHO,
            success=True,
        )

        strategy = BatchResultStrategy()
        results = strategy.process(
            [batch_result],
            context_map=context_map,
            agent_config=agent_config,
        )

        # The result should contain a record with _parse_error
        assert len(results) >= 1
        data = results[0].data
        assert len(data) >= 1
        record = data[0]
        content = record.get("content", record)
        # The content namespace for the action should contain _parse_error
        action_ns = content.get(agent_config["action_name"], content)
        assert "_parse_error" in action_ns or "_parse_error" in record
        assert any("Schema-echo" in str(v) for v in action_ns.values()) or any(
            "Schema-echo" in str(v) for v in record.values()
        )

    def test_valid_output_not_affected(self):
        """Normal LLM output flows through unchanged."""
        custom_id = "tid-002"
        original_row = _make_original_row(custom_id)
        context_map = _make_context_map(custom_id, original_row)
        agent_config = _make_agent_config()

        batch_result = BatchResult(
            custom_id=custom_id,
            content=VALID_OUTPUT,
            success=True,
        )

        strategy = BatchResultStrategy()
        results = strategy.process(
            [batch_result],
            context_map=context_map,
            agent_config=agent_config,
        )

        assert len(results) >= 1
        data = results[0].data
        assert len(data) >= 1
        record = data[0]
        content = record.get("content", record)
        action_ns = content.get(agent_config["action_name"], content)
        assert "_parse_error" not in action_ns
        assert "distractor_explanation_1" in action_ns

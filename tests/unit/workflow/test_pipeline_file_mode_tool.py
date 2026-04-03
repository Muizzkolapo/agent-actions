"""Tests for FILE granularity tool pipeline behavior."""

from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.llm.providers.tools.client import ToolClient
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline


def _make_pipeline_and_context():
    """Create a minimal pipeline and context for FILE-mode tool tests."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config={"kind": "tool", "granularity": "file"},
            action_name="my_file_tool",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name="my_file_tool",
    )
    return pipeline, context


# --- FileUDFResult unwrapping ---


def test_file_udf_result_unwrapped():
    """FILE tool returning FileUDFResult should have .outputs extracted."""
    pipeline, context = _make_pipeline_and_context()

    udf_result = FileUDFResult(
        outputs=[{"name": "alice"}, {"name": "bob"}],
        source_mapping={0: 0, 1: 1},
        input_count=2,
    )

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(udf_result, True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 2
    assert result.data[0]["content"]["name"] == "alice"
    assert result.data[1]["content"]["name"] == "bob"


def test_file_tool_plain_list_still_works():
    """FILE tool returning a plain list should still work (backwards compat)."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [{"source_guid": "sg-1", "content": {"id": 1}}]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"score": 0.9}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    assert len(results) == 1
    assert results[0].status == ProcessingStatus.SUCCESS
    assert results[0].data[0]["content"]["score"] == 0.9


# --- Empty tool output detection ---


def test_file_tool_empty_response_with_input_returns_failed():
    """Tool returning [] with non-empty input returns ProcessingResult.failed()."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    assert len(results) == 1
    assert results[0].status == ProcessingStatus.FAILED
    assert "returned empty result" in results[0].error
    assert "2 input record(s)" in results[0].error


def test_file_tool_empty_response_with_empty_input_ok():
    """Tool returning [] with empty input should NOT be marked failed."""
    pipeline, context = _make_pipeline_and_context()

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([], True),
    ):
        results = pipeline._process_file_mode_tool([], [], context)

    assert len(results) == 1
    assert results[0].status == ProcessingStatus.SUCCESS
    assert results[0].data == []


def test_file_tool_empty_response_feeds_existing_failure_check():
    """Empty tool result -> stats.failed=1 -> existing zero-success check fires."""
    from agent_actions.processing.result_collector import ResultCollector

    pipeline, context = _make_pipeline_and_context()
    input_data = [{"content": {"a": 1}}, {"content": {"b": 2}}]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    output, stats = ResultCollector.collect_results(
        results,
        {"kind": "tool"},
        "my_file_tool",
        is_first_stage=False,
    )

    assert stats.failed == 1
    assert stats.success == 0
    assert output == []


# --- Error surfacing ---


def test_file_mode_error_surfaces():
    """FILE tool raising exception should propagate, not produce empty output."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [{"source_guid": "sg-1", "content": {"id": 1}}]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        side_effect=RuntimeError("connection refused"),
    ):
        with pytest.raises(AgentActionsError, match="connection refused"):
            pipeline._process_file_mode_tool(input_data, input_data, context)


def test_file_mode_error_includes_context():
    """The surfaced error should include agent_name and record_count."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [{"content": {"a": 1}}, {"content": {"b": 2}}]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        side_effect=ValueError("bad data"),
    ):
        with pytest.raises(AgentActionsError) as exc_info:
            pipeline._process_file_mode_tool(input_data, input_data, context)

    assert exc_info.value.context["agent_name"] == "my_file_tool"
    assert exc_info.value.context["record_count"] == 2


# --- _strip_internal_fields list handling ---


def test_strip_internal_fields_handles_list():
    """List of records should have internal fields stripped from each item."""
    data = [
        {"name": "alice", "_batch_filter_status": "included", "_batch_filter_phase": "phase1"},
        {"name": "bob", "_passthrough_fields": {"extra": "data"}},
        "plain_string_item",
    ]

    result = ToolClient._strip_internal_fields(data)

    assert isinstance(result, list)
    assert len(result) == 3
    # Internal fields removed from dicts
    assert "_batch_filter_status" not in result[0]
    assert "_batch_filter_phase" not in result[0]
    assert result[0]["name"] == "alice"
    assert "_passthrough_fields" not in result[1]
    assert result[1]["name"] == "bob"
    # Non-dict items passed through unchanged
    assert result[2] == "plain_string_item"


def test_strip_internal_fields_dict_unchanged():
    """Dict input should still work (regression check)."""
    data = {"name": "alice", "_batch_filter_status": "pass"}

    result = ToolClient._strip_internal_fields(data)

    assert isinstance(result, dict)
    assert "_batch_filter_status" not in result
    assert result["name"] == "alice"


def test_strip_internal_fields_str_unchanged():
    """String input should still work (regression check)."""
    data = '{"name": "alice", "_batch_filter_status": "pass"}'

    result = ToolClient._strip_internal_fields(data)

    assert isinstance(result, str)
    assert "_batch_filter_status" not in result
    assert "alice" in result


# --- _validate_udf_output list handling across granularities ---


_SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def test_validate_udf_output_handles_list_for_record_granularity():
    """RECORD UDF returning a list should validate each item individually."""
    from agent_actions.utils.udf_management.tooling import _validate_udf_output

    result = [{"name": "alice"}, {"name": "bob"}]

    # Should not raise — each item is valid against the schema
    _validate_udf_output("my_tool", result, _SIMPLE_SCHEMA)


def test_validate_udf_output_handles_list_for_file_granularity():
    """FILE UDF returning a FileUDFResult with list validates each item (regression)."""
    from agent_actions.utils.udf_management.tooling import _validate_udf_output

    result = FileUDFResult(
        outputs=[{"name": "alice"}, {"name": "bob"}],
        source_mapping={0: 0, 1: 1},
        input_count=2,
    )

    # Should not raise — FileUDFResult.outputs unwrapped, each item validated
    _validate_udf_output("my_tool", result, _SIMPLE_SCHEMA)


def test_validate_udf_output_rejects_invalid_items_in_list():
    """Invalid item in a list should raise SchemaValidationError referencing item index."""
    from agent_actions.errors import SchemaValidationError
    from agent_actions.utils.udf_management.tooling import _validate_udf_output

    result = [{"name": "alice"}, {"bad_field": 123}]  # item 1 missing 'name'

    with pytest.raises(SchemaValidationError, match="item 1"):
        _validate_udf_output("my_tool", result, _SIMPLE_SCHEMA)


# --- Array schema: json_output_schema is per-item at compile time ---

# For `schema: {type: array, items: {…}}`, _compile_output_schema stores
# the items schema directly as json_output_schema (no wrapper).
_ARRAY_ITEM_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def test_validate_udf_output_array_schema_validates_per_item():
    """Array schema compiled to item schema — each list item validated individually."""
    from agent_actions.utils.udf_management.tooling import _validate_udf_output

    result = [{"name": "alice"}, {"name": "bob"}]

    # Should not raise — each item matches the item schema
    _validate_udf_output("my_tool", result, _ARRAY_ITEM_SCHEMA)


def test_validate_udf_output_array_schema_rejects_invalid_item():
    """Invalid item against array item schema should raise with item index."""
    from agent_actions.errors import SchemaValidationError
    from agent_actions.utils.udf_management.tooling import _validate_udf_output

    result = [{"name": "alice"}, {"bad_field": 123}]  # item 1 missing 'name'

    with pytest.raises(SchemaValidationError, match="item 1"):
        _validate_udf_output("my_tool", result, _ARRAY_ITEM_SCHEMA)


def test_compile_output_schema_extracts_array_items():
    """_compile_output_schema should store items schema for array-type schemas."""
    from agent_actions.output.response.expander import ActionExpander

    agent = {"agent_type": "my_tool"}
    agent["schema"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    }

    ActionExpander._compile_output_schema(agent, {})

    # json_output_schema is the per-item schema with additionalProperties enforced
    assert agent["json_output_schema"] == {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
        "additionalProperties": False,
    }


def test_compile_output_schema_non_array_unchanged():
    """Non-array schemas compile through the standard path."""
    from agent_actions.output.response.expander import ActionExpander

    agent = {"agent_type": "my_tool"}
    agent["schema"] = [
        {"id": "name", "type": "string", "required": True},
    ]

    ActionExpander._compile_output_schema(agent, {})

    # Standard compilation: top-level object with properties
    assert agent["json_output_schema"]["type"] == "object"
    assert "name" in agent["json_output_schema"]["properties"]


# --- RECORD tool list expansion: end-to-end through processor ---


def test_record_tool_list_return_produces_multiple_output_items():
    """RECORD tool returning a list should produce multiple items in ProcessingResult.

    This exercises the full path:
      UDF returns [item1, item2, item3]
        → _transform_response() → PassthroughTransformer
        → DefaultStructureStrategy → DataTransformer.transform_structure()
        → ProcessingResult.success(data=[...])  — 3 items
        → ResultCollector.collect_results() extends output  — 3 items total
    """
    from agent_actions.processing.invocation.result import InvocationResult
    from agent_actions.processing.processor import RecordProcessor
    from agent_actions.processing.result_collector import ResultCollector
    from agent_actions.processing.types import ProcessingContext, ProcessingStatus

    # A RECORD tool config (kind=tool, granularity=record)
    agent_config = {"kind": "tool", "granularity": "record"}
    agent_name = "flatten_tool"

    # Mock strategy that returns a list (1-to-many expansion)
    class ListReturningStrategy:
        def invoke(self, task, context):
            return InvocationResult.immediate(
                response=[
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2", "answer": "A2"},
                    {"question": "Q3", "answer": "A3"},
                ],
                executed=True,
            )

        def supports_recovery(self):
            return False

    processor = RecordProcessor(agent_config, agent_name, strategy=ListReturningStrategy())

    # Single input record (typical RECORD mode item)
    item = {"source_guid": "sg-1", "content": {"raw_questions": "..."}}
    context = ProcessingContext(agent_config=agent_config, agent_name=agent_name)

    # Process single item
    result = processor.process(item, context)

    # Verify the result contains all 3 expanded items
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 3
    contents = [r["content"] for r in result.data]
    assert contents[0] == {"question": "Q1", "answer": "A1"}
    assert contents[1] == {"question": "Q2", "answer": "A2"}
    assert contents[2] == {"question": "Q3", "answer": "A3"}

    # Verify all items have proper source_guid
    for item_out in result.data:
        assert item_out["source_guid"] == "sg-1"

    # Verify ResultCollector flattens correctly
    output, _ = ResultCollector.collect_results(
        [result], agent_config, agent_name, is_first_stage=False
    )
    assert len(output) == 3
    assert output[0]["content"]["question"] == "Q1"
    assert output[2]["content"]["question"] == "Q3"


# --- SchemaValidationError re-raise in process_batch ---


def test_process_batch_reraises_schema_validation_error():
    """SchemaValidationError from process() should propagate through process_batch."""
    from agent_actions.errors import SchemaValidationError
    from agent_actions.processing.invocation.result import InvocationResult
    from agent_actions.processing.processor import RecordProcessor

    agent_config = {"kind": "tool", "granularity": "record"}
    agent_name = "schema_test_tool"

    class SchemaFailingStrategy:
        def invoke(self, task, context):
            return InvocationResult.immediate(
                response={"name": "alice"},
                executed=True,
            )

        def supports_recovery(self):
            return False

    processor = RecordProcessor(agent_config, agent_name, strategy=SchemaFailingStrategy())
    context = ProcessingContext(agent_config=agent_config, agent_name=agent_name)

    items = [{"source_guid": "sg-1", "content": {"id": 1}}]

    with patch.object(
        processor,
        "process",
        side_effect=SchemaValidationError("output doesn't match schema"),
    ):
        with pytest.raises(SchemaValidationError, match="output doesn't match schema"):
            processor.process_batch(items, context)


# --- ResultCollector failure handling ---


def test_result_collector_does_not_raise_on_partial_failure():
    """Mix of SUCCESS + FAILED should return output without raising."""
    from agent_actions.processing.result_collector import ResultCollector
    from agent_actions.processing.types import ProcessingResult

    results = [
        ProcessingResult.success(data=[{"content": {"val": 1}}]),
        ProcessingResult.failed(error="connection timeout"),
    ]

    output, _ = ResultCollector.collect_results(
        results,
        agent_config={"kind": "tool"},
        agent_name="partial_tool",
        is_first_stage=False,
    )

    assert len(output) == 1
    assert output[0]["content"]["val"] == 1


def test_result_collector_does_not_raise_when_all_filtered():
    """All FILTERED results should return empty output without raising."""
    from agent_actions.processing.result_collector import ResultCollector
    from agent_actions.processing.types import ProcessingResult

    results = [
        ProcessingResult.filtered(),
        ProcessingResult.filtered(),
    ]

    output, _ = ResultCollector.collect_results(
        results,
        agent_config={"kind": "tool"},
        agent_name="filter_tool",
        is_first_stage=False,
    )

    assert output == []

"""Tests for FILE granularity tool pipeline behavior."""

from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.llm.providers.tools.client import ToolClient
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline


def _make_pipeline_and_context(action_name="my_file_tool", *, idx=0, is_first_stage=True):
    """Create a minimal pipeline and context for FILE-mode tool tests."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config={"kind": "tool", "granularity": "file"},
            action_name=action_name,
            idx=idx,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name=action_name,
        is_first_stage=is_first_stage,
    )
    return pipeline, context


# --- FileUDFResult unwrapping ---


def test_file_udf_result_unwrapped():
    """FILE tool returning FileUDFResult should have .outputs extracted."""
    pipeline, context = _make_pipeline_and_context()

    udf_result = FileUDFResult(
        outputs=[{"name": "alice"}, {"name": "bob"}],
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


def test_file_udf_result_source_mapping_auto_inferred():
    """Framework always infers source_mapping — tools never provide it."""
    pipeline, context = _make_pipeline_and_context()

    udf_result = FileUDFResult(
        outputs=[{"name": "alice"}, {"name": "bob"}],
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

    # Framework inferred identity mapping (2 in, 2 out)
    assert results[0].source_mapping == {0: 0, 1: 1}


def test_file_tool_plain_list_auto_infers_identity_mapping():
    """Plain list return with same count auto-infers identity source_mapping."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [{"source_guid": "sg-1", "content": {"id": 1}}]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"score": 0.9}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Auto-inferred identity mapping (same input/output count)
    assert results[0].source_mapping == {0: 0}


def test_file_udf_result_mapping_always_inferred():
    """FileUDFResult triggers framework-inferred mapping like plain lists."""
    pipeline, context = _make_pipeline_and_context()

    udf_result = FileUDFResult(outputs=[{"name": "alice"}])

    input_data = [{"source_guid": "sg-1", "content": {"id": 1}}]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(udf_result, True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Framework inferred identity mapping (1 in, 1 out)
    assert results[0].source_mapping == {0: 0}


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
    agent_config = {
        "kind": "tool",
        "granularity": "record",
        "context_scope": {"observe": ["source.*"]},
    }
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


# --- FILE-mode source_guid metadata sovereignty ---


def test_file_tool_plain_list_preserves_source_guid():
    """Plain list tool output gets source_guid from input via identity mapping."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
    ]

    # Tool returns plain list — no source_guid, no FileUDFResult
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"score": 0.9}, {"score": 0.8}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    assert result.data[0]["source_guid"] == "sg-1"
    assert result.data[1]["source_guid"] == "sg-2"


def test_file_tool_filter_fewer_outputs_uses_first_source_guid():
    """When tool filters N→fewer with mixed source_guids, all outputs get first input's source_guid."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
        {"source_guid": "sg-3", "content": {"id": 3}},
    ]

    # Tool filters 3→2 (no mapping — framework can't know which were kept)
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"name": "alice"}, {"name": "charlie"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    # All outputs get first input's source_guid (framework fallback)
    assert result.data[0]["source_guid"] == "sg-1"
    assert result.data[1]["source_guid"] == "sg-1"


def test_file_tool_shared_source_guid_broadcast():
    """When all inputs share source_guid, all outputs inherit it regardless of cardinality."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-shared", "content": {"q": "A"}},
        {"source_guid": "sg-shared", "content": {"q": "B"}},
    ]

    # Tool returns different count — no explicit mapping
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"q": "A1"}, {"q": "A2"}, {"q": "B1"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # All outputs inherit the shared source_guid
    for item in results[0].data:
        assert item["source_guid"] == "sg-shared"


def test_file_tool_cardinality_change_without_mapping_still_sets_source_guid(capsys):
    """N→M without mapping still sets source_guid on all outputs."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"q": "A"}},
        {"source_guid": "sg-2", "content": {"q": "B"}},
    ]

    # Tool returns different count, mixed source_guids, no mapping
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"q": "X"}, {"q": "Y"}, {"q": "Z"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Warning emitted about cardinality change (to stderr via logger)
    captured = capsys.readouterr()
    assert "changed cardinality" in captured.err

    # All outputs still have source_guid (not empty, not None)
    for item in results[0].data:
        assert item.get("source_guid"), f"source_guid missing or empty: {item}"


def test_file_tool_source_guid_never_empty_string():
    """No output item should ever have source_guid='' after FILE-mode processing."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"result": "ok"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    for item in results[0].data:
        assert item.get("source_guid") != "", "source_guid must not be empty string"
        assert item.get("source_guid") == "sg-1"


def test_file_tool_tool_explicit_source_guid_respected():
    """If tool explicitly returns source_guid, framework respects it."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-input", "content": {"id": 1}},
    ]

    # Tool explicitly sets source_guid in its output
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"result": "ok", "source_guid": "sg-tool-set"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Tool's explicit value wins over framework reattachment
    assert results[0].data[0]["source_guid"] == "sg-tool-set"


# --- Hardening: edge cases that must never break source_guid ---


def test_file_tool_mixed_source_guid_some_set_some_not():
    """Tool returns mix of items with and without source_guid — framework fills gaps."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
        {"source_guid": "sg-3", "content": {"id": 3}},
    ]

    # Tool sets source_guid on item[1] but not on [0] or [2]
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(
            [{"val": "a"}, {"val": "b", "source_guid": "sg-tool-explicit"}, {"val": "c"}],
            True,
        ),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    # Item 0: no explicit source_guid → framework reattaches from input[0]
    assert result.data[0]["source_guid"] == "sg-1"
    # Item 1: tool explicitly set it → respected
    assert result.data[1]["source_guid"] == "sg-tool-explicit"
    # Item 2: no explicit source_guid → framework reattaches from input[2]
    assert result.data[2]["source_guid"] == "sg-3"


def test_file_tool_empty_input_empty_output():
    """Empty input + empty output → no crash, no source_guid issues."""
    pipeline, context = _make_pipeline_and_context()

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([], True),
    ):
        results = pipeline._process_file_mode_tool([], [], context)

    assert results[0].status == ProcessingStatus.SUCCESS
    assert results[0].data == []


def test_file_tool_input_without_source_guid():
    """Input records missing source_guid entirely — no crash, outputs have empty/absent source_guid."""
    pipeline, context = _make_pipeline_and_context()

    # Input records with no source_guid at all (possible in edge cases)
    input_data = [
        {"content": {"id": 1}},
        {"content": {"id": 2}},
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"score": 0.9}, {"score": 0.8}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Should not crash — source_guid just won't be set by reattachment
    assert results[0].status == ProcessingStatus.SUCCESS
    assert len(results[0].data) == 2


def test_file_tool_non_dict_output_items():
    """Non-dict items in tool output don't crash source_guid reattachment."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
    ]

    # Tool returns a non-dict item (string)
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(["just a string"], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Non-dict wrapped as {"content": {"value": ...}} — source_guid reattached
    assert results[0].data[0]["source_guid"] == "sg-1"
    assert results[0].data[0]["content"]["value"] == "just a string"


def test_file_tool_merge_reduces_to_fewer_outputs():
    """N→fewer merge: framework broadcasts first input's source_guid."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"q": "A"}},
        {"source_guid": "sg-2", "content": {"q": "B"}},
        {"source_guid": "sg-3", "content": {"q": "C"}},
    ]

    # Tool merges 3→2 (framework can't know which merged)
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"merged": "AB"}, {"single": "C"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    # All outputs get first input's source_guid (fallback for mixed guids)
    for item in result.data:
        assert item["source_guid"] == "sg-1"


def test_file_tool_large_cardinality_expansion():
    """1→N expansion: all outputs inherit the single input's source_guid."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-only", "content": {"nested": [1, 2, 3, 4, 5]}},
    ]

    # Tool explodes 1 input into 5 outputs
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"val": i} for i in range(5)], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # All 5 outputs inherit the single input's source_guid (shared-source shortcut)
    for item in results[0].data:
        assert item["source_guid"] == "sg-only"


# --- Hardening: _infer_source_mapping unit tests ---


class TestInferSourceMapping:
    """Edge-case unit tests for _infer_source_mapping.

    Core tier coverage (identity, node-id, content, heuristic) lives in
    tests/unit/workflow/test_file_mode_source_mapping.py.
    """

    def test_zero_output_returns_empty_mapping(self):
        from agent_actions.workflow.pipeline_file_mode import _infer_source_mapping

        result = _infer_source_mapping(
            output_count=0,
            input_data=[{"source_guid": "sg-1"}],
            action_name="test",
        )
        assert result == {}

    def test_zero_input_returns_identity_if_zero_output(self):
        from agent_actions.workflow.pipeline_file_mode import _infer_source_mapping

        result = _infer_source_mapping(
            output_count=0,
            input_data=[],
            action_name="test",
        )
        assert result == {}

    def test_input_without_source_guid_falls_to_broadcast(self):
        from agent_actions.workflow.pipeline_file_mode import _infer_source_mapping

        result = _infer_source_mapping(
            output_count=3,
            input_data=[{"content": "no guid"}, {"content": "also none"}],
            action_name="test",
        )
        # No source_guids → empty set → len != 1 → falls to broadcast warning
        assert result == {0: 0, 1: 0, 2: 0}


# --- Hardening: _reattach_source_guid unit tests ---


class TestReattachSourceGuid:
    """Direct unit tests for _reattach_source_guid logic."""

    def test_reattaches_from_mapping(self):
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        structured = [{"content": {"val": 1}}, {"content": {"val": 2}}]
        mapping = {0: 0, 1: 1}
        original = [{"source_guid": "sg-a"}, {"source_guid": "sg-b"}]

        _reattach_source_guid(structured, mapping, original)

        assert structured[0]["source_guid"] == "sg-a"
        assert structured[1]["source_guid"] == "sg-b"

    def test_respects_existing_source_guid(self):
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        structured = [
            {"content": {"val": 1}, "source_guid": "sg-already-set"},
        ]
        mapping = {0: 0}
        original = [{"source_guid": "sg-input"}]

        _reattach_source_guid(structured, mapping, original)

        assert structured[0]["source_guid"] == "sg-already-set"

    def test_no_crash_on_none_mapping(self):
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        structured = [{"content": {"val": 1}}]
        _reattach_source_guid(structured, None, [{"source_guid": "sg-1"}])
        assert "source_guid" not in structured[0]

    def test_no_crash_on_empty_original(self):
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        structured = [{"content": {"val": 1}}]
        _reattach_source_guid(structured, {0: 0}, [])
        assert "source_guid" not in structured[0]

    def test_many_to_one_uses_first_parent(self):
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        structured = [{"content": {"merged": True}}]
        mapping = {0: [0, 1, 2]}
        original = [
            {"source_guid": "sg-first"},
            {"source_guid": "sg-second"},
            {"source_guid": "sg-third"},
        ]

        _reattach_source_guid(structured, mapping, original)

        assert structured[0]["source_guid"] == "sg-first"

    def test_out_of_bounds_index_skipped(self):
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        structured = [{"content": {"val": 1}}]
        mapping = {0: 99}  # Out of bounds
        original = [{"source_guid": "sg-only"}]

        _reattach_source_guid(structured, mapping, original)

        # Out of bounds → not set (no crash)
        assert "source_guid" not in structured[0]


# ---------------------------------------------------------------------------
# Integration: dedup with shared source_guid through full pipeline
# ---------------------------------------------------------------------------


class TestDedupSharedGuidLineage:
    """Deterministic integration tests proving each output record gets distinct
    lineage after a dedup tool reduces cardinality on shared-source_guid data.

    These tests exercise the full path: process_file_mode_tool → inference →
    enrichment → lineage assignment. They verify the fix for the bug where
    all outputs inherited input[0]'s lineage.
    """

    def test_dedup_shared_guid_distinct_lineage_via_content_match(self):
        """7 inputs (shared guid) → 6 outputs via dedup → each output gets
        its own parent's lineage, not all from input[0].

        This reproduces the exact bug from the report: observe-filtered data
        (no node_id), content fingerprint matching resolves the correct parent.
        """
        pipeline, context = _make_pipeline_and_context("dedup_tool", idx=1, is_first_stage=False)

        # 7 input records from the same source page — all share source_guid.
        # Each has a distinct lineage from a prior flatten step.
        original_data = [
            {
                "source_guid": "sg-page1",
                "node_id": f"flatten_q{i}",
                "lineage": [f"flatten_q{i}"],
                "target_id": f"tid-{i}",
                "content": {"question": f"Q{i}", "idx": i},
            }
            for i in range(7)
        ]
        # Observe-filtered data the tool receives (flat dicts, no framework fields).
        observe_filtered = [{"question": f"Q{i}", "idx": i} for i in range(7)]

        # Dedup tool drops record 6 (duplicate). Returns 6 records.
        dedup_output = [{"question": f"Q{i}", "idx": i} for i in range(6)]

        context.source_data = original_data

        with patch(
            "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
            return_value=(dedup_output, True),
        ):
            results = pipeline._process_file_mode_tool(observe_filtered, original_data, context)

        result = results[0]
        assert result.status == ProcessingStatus.SUCCESS
        assert len(result.data) == 6

        # CRITICAL ASSERTION: each output traces to its CORRECT parent.
        # Before fix: all outputs had lineage from input[0] (flatten_q0).
        # After fix: output[i] has lineage from input[i] (flatten_q{i}).
        for i, item in enumerate(result.data):
            lineage = item.get("lineage", [])
            # Lineage must contain the parent's node_id (flatten_q{i}).
            assert f"flatten_q{i}" in lineage, (
                f"output[{i}] lineage {lineage} missing expected parent flatten_q{i}"
            )
            # Must also contain this action's own node_id.
            assert any(nid.startswith("dedup_tool_") for nid in lineage), (
                f"output[{i}] lineage {lineage} missing own node_id"
            )

        # Verify ALL outputs have distinct lineage (no two share the same chain).
        lineage_tuples = [tuple(item["lineage"]) for item in result.data]
        assert len(set(lineage_tuples)) == 6, (
            f"Expected 6 distinct lineage chains, got {len(set(lineage_tuples))}"
        )

    def test_dedup_shared_guid_distinct_lineage_via_node_id_match(self):
        """Same scenario but tool receives full records (no observe filter)
        and passes them through with node_id intact → node_id matching fires.
        """
        pipeline, context = _make_pipeline_and_context("dedup_tool", idx=1, is_first_stage=False)

        # Full records with framework metadata.
        original_data = [
            {
                "source_guid": "sg-page1",
                "node_id": f"flatten_q{i}",
                "lineage": [f"flatten_q{i}"],
                "target_id": f"tid-{i}",
                "content": {"question": f"Q{i}", "idx": i},
            }
            for i in range(7)
        ]

        # Tool receives full records and returns a subset (drops record 3).
        # Since no observe filter, output carries node_id.
        dedup_output = [
            {
                "node_id": f"flatten_q{i}",
                "source_guid": "sg-page1",
                "question": f"Q{i}",
                "idx": i,
            }
            for i in range(7)
            if i != 3
        ]

        context.source_data = original_data

        with patch(
            "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
            return_value=(dedup_output, True),
        ):
            results = pipeline._process_file_mode_tool(original_data, original_data, context)

        result = results[0]
        assert result.status == ProcessingStatus.SUCCESS
        assert len(result.data) == 6

        # Verify mapping jumped over input[3] correctly.
        assert result.source_mapping == {0: 0, 1: 1, 2: 2, 3: 4, 4: 5, 5: 6}

        # Each output traces to the correct parent — output[3] → input[4].
        expected_parents = [0, 1, 2, 4, 5, 6]
        for out_idx, in_idx in enumerate(expected_parents):
            lineage = result.data[out_idx].get("lineage", [])
            assert f"flatten_q{in_idx}" in lineage, (
                f"output[{out_idx}] lineage {lineage} missing expected parent flatten_q{in_idx}"
            )

    def test_dedup_reorder_shared_guid_content_match(self):
        """Dedup reorders output — content matching correctly maps non-sequential."""
        pipeline, context = _make_pipeline_and_context("dedup_tool", idx=1, is_first_stage=False)

        original_data = [
            {
                "source_guid": "sg-A",
                "node_id": f"flatten_{i}",
                "lineage": [f"flatten_{i}"],
                "target_id": f"tid-{i}",
                "content": {"q": f"Q{i}", "score": i * 10},
            }
            for i in range(5)
        ]
        observe_filtered = [{"q": f"Q{i}", "score": i * 10} for i in range(5)]

        # Tool returns records [4, 1, 0] in that order (dropped 2 and 3).
        dedup_output = [
            {"q": "Q4", "score": 40},
            {"q": "Q1", "score": 10},
            {"q": "Q0", "score": 0},
        ]

        context.source_data = original_data

        with patch(
            "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
            return_value=(dedup_output, True),
        ):
            results = pipeline._process_file_mode_tool(observe_filtered, original_data, context)

        result = results[0]
        assert len(result.data) == 3

        # output[0] ("Q4") → input[4], output[1] ("Q1") → input[1], etc.
        assert result.source_mapping == {0: 4, 1: 1, 2: 0}

        # Verify lineage reflects the reorder.
        assert "flatten_4" in result.data[0]["lineage"]
        assert "flatten_1" in result.data[1]["lineage"]
        assert "flatten_0" in result.data[2]["lineage"]

        # All lineage chains are distinct.
        chains = [tuple(item["lineage"]) for item in result.data]
        assert len(set(chains)) == 3

    def test_mixed_guid_dedup_falls_to_broadcast(self):
        """When inputs have mixed source_guids and content is transformed,
        inference falls to broadcast (last resort). Verify it doesn't crash
        and produces valid (if imprecise) lineage.
        """
        pipeline, context = _make_pipeline_and_context("dedup_tool", idx=1, is_first_stage=False)

        original_data = [
            {
                "source_guid": f"sg-{i}",
                "node_id": f"flatten_{i}",
                "lineage": [f"flatten_{i}"],
                "target_id": f"tid-{i}",
                "content": {"q": f"Q{i}"},
            }
            for i in range(4)
        ]
        observe_filtered = [{"q": f"Q{i}"} for i in range(4)]

        # Tool transforms AND reduces — no node_id, no content match.
        dedup_output = [{"summary": "merged_A"}, {"summary": "merged_B"}]

        context.source_data = original_data

        with patch(
            "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
            return_value=(dedup_output, True),
        ):
            results = pipeline._process_file_mode_tool(observe_filtered, original_data, context)

        result = results[0]
        assert result.status == ProcessingStatus.SUCCESS
        assert len(result.data) == 2

        # Both outputs should have valid lineage (non-empty).
        for item in result.data:
            assert "lineage" in item
            assert len(item["lineage"]) > 0

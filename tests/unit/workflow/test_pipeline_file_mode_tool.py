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
    assert result.data[0]["content"]["my_file_tool"]["name"] == "alice"
    assert result.data[1]["content"]["my_file_tool"]["name"] == "bob"


def test_file_udf_result_source_mapping_auto_inferred():
    """Framework resolves source_mapping by node_id — tools never provide it."""
    pipeline, context = _make_pipeline_and_context()

    udf_result = FileUDFResult(
        outputs=[{"name": "alice", "node_id": "n1"}, {"name": "bob", "node_id": "n2"}],
    )

    input_data = [
        {"source_guid": "sg-1", "node_id": "n1", "content": {"id": 1}},
        {"source_guid": "sg-2", "node_id": "n2", "content": {"id": 2}},
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(udf_result, True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Framework resolved mapping via node_id
    assert results[0].source_mapping == {0: 0, 1: 1}


def test_file_tool_plain_list_auto_infers_identity_mapping():
    """Plain list return with node_id resolves source_mapping via node_id match."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [{"source_guid": "sg-1", "node_id": "n1", "content": {"id": 1}}]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"score": 0.9, "node_id": "n1"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Resolved mapping via node_id
    assert results[0].source_mapping == {0: 0}


def test_file_udf_result_mapping_always_inferred():
    """FileUDFResult resolves mapping via node_id like plain lists."""
    pipeline, context = _make_pipeline_and_context()

    udf_result = FileUDFResult(outputs=[{"name": "alice", "node_id": "n1"}])

    input_data = [{"source_guid": "sg-1", "node_id": "n1", "content": {"id": 1}}]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(udf_result, True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Framework resolved mapping via node_id
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
    assert results[0].data[0]["content"]["my_file_tool"]["score"] == 0.9


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
        "agent_type": "flatten_tool",
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
    contents = [r["content"]["flatten_tool"] for r in result.data]
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
    assert output[0]["content"]["flatten_tool"]["question"] == "Q1"
    assert output[2]["content"]["flatten_tool"]["question"] == "Q3"


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
    """Plain list tool output gets source_guid from input via node_id mapping."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "node_id": "n1", "content": {"id": 1}},
        {"source_guid": "sg-2", "node_id": "n2", "content": {"id": 2}},
    ]

    # Tool returns plain list with node_id — no source_guid, no FileUDFResult
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"score": 0.9, "node_id": "n1"}, {"score": 0.8, "node_id": "n2"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    assert result.data[0]["source_guid"] == "sg-1"
    assert result.data[1]["source_guid"] == "sg-2"


def test_file_tool_filter_fewer_outputs_with_node_id():
    """When tool filters N→fewer, outputs with node_id get correct source_guid."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "node_id": "n1", "content": {"id": 1}},
        {"source_guid": "sg-2", "node_id": "n2", "content": {"id": 2}},
        {"source_guid": "sg-3", "node_id": "n3", "content": {"id": 3}},
    ]

    # Tool filters 3→2, passes through node_id for matched records
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(
            [{"name": "alice", "node_id": "n1"}, {"name": "charlie", "node_id": "n3"}],
            True,
        ),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    # node_id-based mapping resolves correct source_guids
    assert result.data[0]["source_guid"] == "sg-1"
    assert result.data[1]["source_guid"] == "sg-3"


def test_file_tool_new_records_without_node_id_get_no_source_guid():
    """Tool outputs without node_id are new records — no source_guid reattached."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-shared", "node_id": "n1", "content": {"q": "A"}},
        {"source_guid": "sg-shared", "node_id": "n2", "content": {"q": "B"}},
    ]

    # Tool returns new records (no node_id) — these are new, not passthrough
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"q": "A1"}, {"q": "A2"}, {"q": "B1"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # No node_id in outputs → empty mapping (new records, no parent)
    assert results[0].source_mapping == {}
    # Enrichment pipeline sets source_guid="" on new records (no parent to inherit from)
    for item in results[0].data:
        assert item.get("source_guid") == ""


def test_file_tool_cardinality_change_new_records_get_empty_mapping():
    """N→M with new records (no node_id) produces empty source_mapping."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "node_id": "n1", "content": {"q": "A"}},
        {"source_guid": "sg-2", "node_id": "n2", "content": {"q": "B"}},
    ]

    # Tool returns different count, no node_id → all new records
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"q": "X"}, {"q": "Y"}, {"q": "Z"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # No node_id → empty mapping (new records, no parent)
    assert results[0].source_mapping == {}


def test_file_tool_source_guid_never_empty_string():
    """No output item should ever have source_guid='' after FILE-mode processing."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "node_id": "n1", "content": {"id": 1}},
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"result": "ok", "node_id": "n1"}], True),
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
    """Tool returns mix of items with and without source_guid — framework fills gaps via node_id."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "node_id": "n1", "content": {"id": 1}},
        {"source_guid": "sg-2", "node_id": "n2", "content": {"id": 2}},
        {"source_guid": "sg-3", "node_id": "n3", "content": {"id": 3}},
    ]

    # Tool sets source_guid on item[1] but not on [0] or [2]; node_id on [0] and [2]
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(
            [
                {"val": "a", "node_id": "n1"},
                {"val": "b", "source_guid": "sg-tool-explicit"},
                {"val": "c", "node_id": "n3"},
            ],
            True,
        ),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    # Item 0: no explicit source_guid, node_id matched → framework reattaches from input[0]
    assert result.data[0]["source_guid"] == "sg-1"
    # Item 1: tool explicitly set it → respected (no node_id, so not in mapping)
    assert result.data[1]["source_guid"] == "sg-tool-explicit"
    # Item 2: no explicit source_guid, node_id matched → framework reattaches from input[2]
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
        {"source_guid": "sg-1", "node_id": "n1", "content": {"id": 1}},
    ]

    # Tool returns a non-dict item (string) — no node_id possible, treated as new record
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(["just a string"], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # Non-dict wrapped as {"content": {"value": ...}} — no node_id, so no mapping
    assert results[0].data[0]["content"]["my_file_tool"]["value"] == "just a string"
    # Same cardinality (1:1) — positional fallback propagates source_guid from input
    assert results[0].data[0].get("source_guid") == "sg-1"


def test_file_tool_merge_reduces_to_fewer_outputs():
    """N→fewer merge: new records (no node_id) get empty mapping."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "node_id": "n1", "content": {"q": "A"}},
        {"source_guid": "sg-2", "node_id": "n2", "content": {"q": "B"}},
        {"source_guid": "sg-3", "node_id": "n3", "content": {"q": "C"}},
    ]

    # Tool merges 3→2 — new records with no node_id (aggregation results)
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"merged": "AB"}, {"single": "C"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    # New records — no node_id → empty mapping, no source_guid reattached
    assert result.source_mapping == {}


def test_file_tool_large_cardinality_expansion():
    """1→N expansion: outputs with node_id inherit source_guid, others are new."""
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-only", "node_id": "n1", "content": {"nested": [1, 2, 3, 4, 5]}},
    ]

    # Tool explodes 1 input into 5 new outputs (no node_id — aggregation/expansion)
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"val": i} for i in range(5)], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    # No node_id on outputs → empty mapping (new records)
    assert results[0].source_mapping == {}
    assert len(results[0].data) == 5


# --- Hardening: _resolve_source_mapping unit tests ---


class TestResolveSourceMapping:
    """Direct unit tests for _resolve_source_mapping logic."""

    def test_matches_by_node_id(self):
        from agent_actions.workflow.pipeline_file_mode import _resolve_source_mapping

        result = _resolve_source_mapping(
            raw_outputs=[{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"}],
            input_data=[{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"}],
            action_name="test",
        )
        assert result == {0: 0, 1: 1, 2: 2}

    def test_reordered_outputs_match_correctly(self):
        from agent_actions.workflow.pipeline_file_mode import _resolve_source_mapping

        result = _resolve_source_mapping(
            raw_outputs=[{"node_id": "c"}, {"node_id": "a"}],
            input_data=[{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"}],
            action_name="test",
        )
        assert result == {0: 2, 1: 0}

    def test_no_node_id_in_outputs_returns_empty(self):
        from agent_actions.workflow.pipeline_file_mode import _resolve_source_mapping

        result = _resolve_source_mapping(
            raw_outputs=[{"val": "x"}, {"val": "y"}, {"val": "z"}],
            input_data=[{"node_id": "a"}, {"node_id": "b"}],
            action_name="test",
        )
        # No node_id on outputs → all new records → empty mapping
        assert result == {}

    def test_zero_outputs_returns_empty_mapping(self):
        from agent_actions.workflow.pipeline_file_mode import _resolve_source_mapping

        result = _resolve_source_mapping(
            raw_outputs=[],
            input_data=[{"node_id": "a"}],
            action_name="test",
        )
        assert result == {}

    def test_zero_inputs_returns_empty_mapping(self):
        from agent_actions.workflow.pipeline_file_mode import _resolve_source_mapping

        result = _resolve_source_mapping(
            raw_outputs=[],
            input_data=[],
            action_name="test",
        )
        assert result == {}

    def test_input_without_node_id_not_matchable(self):
        from agent_actions.workflow.pipeline_file_mode import _resolve_source_mapping

        result = _resolve_source_mapping(
            raw_outputs=[{"node_id": "a"}, {"node_id": "b"}],
            input_data=[{"content": "no nid"}, {"content": "also none"}],
            action_name="test",
        )
        # No node_id on inputs → nothing to match → empty mapping
        assert result == {}


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

    def test_unmapped_outputs_not_defaulted_to_first(self):
        """Outputs not in source_mapping must NOT inherit source_guid from input[0]."""
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        # 3 outputs: first two mapped, third unmapped (new record)
        structured = [
            {"content": {"val": 1}},
            {"content": {"val": 2}},
            {"content": {"val": 3}},
        ]
        mapping = {0: 0, 1: 1}  # index 2 NOT in mapping
        original = [
            {"source_guid": "sg-a"},
            {"source_guid": "sg-b"},
            {"source_guid": "sg-c"},
        ]

        _reattach_source_guid(structured, mapping, original)

        assert structured[0]["source_guid"] == "sg-a"
        assert structured[1]["source_guid"] == "sg-b"
        # Index 2 is unmapped — must NOT get sg-a (the old default-to-0 bug)
        assert "source_guid" not in structured[2]

    def test_empty_mapping_positional_fallback_same_cardinality(self):
        """Empty source_mapping with same cardinality uses positional fallback."""
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        structured = [{"content": {"val": 1}}, {"content": {"val": 2}}]
        mapping: dict = {}  # Empty — no node_id matches
        original = [{"source_guid": "sg-a"}, {"source_guid": "sg-b"}]

        _reattach_source_guid(structured, mapping, original)

        assert structured[0]["source_guid"] == "sg-a"
        assert structured[1]["source_guid"] == "sg-b"

    def test_empty_mapping_no_fallback_different_cardinality(self):
        """Empty source_mapping with different cardinality does NOT reattach."""
        from agent_actions.workflow.pipeline_file_mode import _reattach_source_guid

        structured = [
            {"content": {"val": 1}},
            {"content": {"val": 2}},
            {"content": {"val": 3}},
        ]
        mapping: dict = {}  # Empty — no node_id matches
        original = [{"source_guid": "sg-a"}, {"source_guid": "sg-b"}]

        _reattach_source_guid(structured, mapping, original)

        # Cardinality mismatch (3 vs 2): no safe positional fallback
        for item in structured:
            assert "source_guid" not in item


# --- Bug 1: Content preservation when tool returns full records ---


def test_file_tool_full_record_content_preserved():
    """FILE tool returning records with node_id + populated content must preserve content.

    Regression test for content stripping bug: framework must not replace
    the tool's content dict with {} when re-wrapping the record.
    """
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {
            "source_guid": "sg-1",
            "node_id": "flatten_q_0",
            "lineage": ["extract_abc_0", "flatten_q_0"],
            "content": {"question_text": "What is X?", "answer_text": "X is Y."},
        },
        {
            "source_guid": "sg-1",
            "node_id": "flatten_q_1",
            "lineage": ["extract_abc_0", "flatten_q_1"],
            "content": {"question_text": "What is Z?", "answer_text": "Z is W."},
        },
    ]

    # Tool returns original records (passthrough/filter pattern) — content populated
    tool_output = [
        {
            "node_id": "flatten_q_0",
            "source_guid": "sg-1",
            "lineage": ["extract_abc_0", "flatten_q_0"],
            "content": {"question_text": "What is X?", "answer_text": "X is Y."},
        },
        {
            "node_id": "flatten_q_1",
            "source_guid": "sg-1",
            "lineage": ["extract_abc_0", "flatten_q_1"],
            "content": {"question_text": "What is Z?", "answer_text": "Z is W."},
        },
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(tool_output, True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 2

    assert result.data[0]["content"]["my_file_tool"]["question_text"] == "What is X?"
    assert result.data[0]["content"]["my_file_tool"]["answer_text"] == "X is Y."
    assert result.data[1]["content"]["my_file_tool"]["question_text"] == "What is Z?"
    assert result.data[1]["content"]["my_file_tool"]["answer_text"] == "Z is W."


# --- Bug 2: Lineage collision with shared source_guid ---


def test_file_tool_shared_source_guid_each_output_gets_correct_mapping():
    """When inputs share source_guid, node_id-based mapping must resolve each correctly.

    Regression test for lineage collision: shared source_guid must NOT cause
    all outputs to inherit the first input's lineage.
    """
    pipeline, context = _make_pipeline_and_context()

    # 5 inputs from same source page (shared source_guid), each with unique node_id
    input_data = [
        {"source_guid": "sg-shared", "node_id": f"flatten_q_{i}", "content": {"q": f"Q{i}"}}
        for i in range(5)
    ]

    # Tool deduplicates 5→4, returns records with original node_ids
    tool_output = [
        {"node_id": "flatten_q_0", "source_guid": "sg-shared", "content": {"q": "Q0"}},
        {"node_id": "flatten_q_1", "source_guid": "sg-shared", "content": {"q": "Q1"}},
        {"node_id": "flatten_q_3", "source_guid": "sg-shared", "content": {"q": "Q3"}},
        {"node_id": "flatten_q_4", "source_guid": "sg-shared", "content": {"q": "Q4"}},
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(tool_output, True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    assert result.source_mapping == {0: 0, 1: 1, 2: 3, 3: 4}

    for item in result.data:
        assert item["source_guid"] == "sg-shared"


# --- Bug 3: Synthesis lineage via copy pattern ---


def test_file_tool_copy_pattern_preserves_lineage():
    """Tool using copy pattern (copy record + replace content) must extend lineage.

    The copy pattern preserves node_id from the input record, so the framework
    matches the output to its input and extends the lineage chain. This is the
    recommended approach for mid-pipeline FILE tools that transform data.
    """
    pipeline, context = _make_pipeline_and_context()

    input_data = [
        {
            "source_guid": "sg-1",
            "node_id": "extract_abc_0",
            "lineage": ["ingest_xyz_0", "extract_abc_0"],
            "content": {"raw_text": "original content"},
        },
        {
            "source_guid": "sg-2",
            "node_id": "extract_abc_1",
            "lineage": ["ingest_xyz_1", "extract_abc_1"],
            "content": {"raw_text": "other content"},
        },
    ]

    # Enrichment needs source_data for parent lookup (set by pipeline.py in real flow)
    context.source_data = input_data

    # Tool copies input records and replaces content (synthesis-via-copy pattern)
    tool_output = [
        {
            "node_id": "extract_abc_0",  # preserved from input
            "source_guid": "sg-1",
            "content": {"transformed": "new value from original"},  # replaced content
        },
        {
            "node_id": "extract_abc_1",  # preserved from input
            "source_guid": "sg-2",
            "content": {"transformed": "new value from other"},  # replaced content
        },
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(tool_output, True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS

    assert result.source_mapping == {0: 0, 1: 1}

    assert result.data[0]["content"]["my_file_tool"]["transformed"] == "new value from original"
    assert result.data[1]["content"]["my_file_tool"]["transformed"] == "new value from other"

    assert result.data[0]["source_guid"] == "sg-1"
    assert result.data[1]["source_guid"] == "sg-2"

    # Lineage must be extended from parent, not truncated to just [self]
    for i, item in enumerate(result.data):
        lineage = item.get("lineage", [])
        # Parent lineage had 2 entries; enrichment appends new node_id → at least 3
        assert len(lineage) >= 3, f"item[{i}] lineage not extended from parent: {lineage}"


# --- FILE HITL RecordEnvelope tests ---


def _make_hitl_pipeline_and_context():
    """Create a minimal pipeline and context for FILE-mode HITL tests."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review_answers",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_answers",
    )
    return pipeline, context


def test_file_hitl_namespaces_output_under_action():
    """FILE HITL wraps output under action namespace, not flat into content."""
    pipeline, context = _make_hitl_pipeline_and_context()

    input_data = [
        {
            "source_guid": "sg-1",
            "content": {
                "source": {"page_content": "..."},
                "extract": {"question_text": "Why?"},
            },
        },
    ]

    decision = {"hitl_status": "approved", "user_comment": "Looks good", "timestamp": "2026-01-01"}

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([decision], True),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    content = result.data[0]["content"]

    # HITL output is under the action namespace
    assert "review_answers" in content
    ns = content["review_answers"]
    assert ns["hitl_status"] == "approved"
    assert ns["user_comment"] == "Looks good"

    # HITL fields are NOT flat in content
    assert "hitl_status" not in content
    assert "user_comment" not in content


def test_file_hitl_preserves_upstream_namespaces():
    """FILE HITL preserves all upstream namespaces from input records."""
    pipeline, context = _make_hitl_pipeline_and_context()

    input_data = [
        {
            "source_guid": "sg-1",
            "content": {
                "source": {"page_content": "doc text"},
                "extract": {"question_text": "Why?"},
                "summarize": {"summary": "short version"},
            },
        },
    ]

    decision = {"hitl_status": "approved"}

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([decision], True),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    content = results[0].data[0]["content"]
    assert "source" in content
    assert "extract" in content
    assert "summarize" in content
    assert content["source"]["page_content"] == "doc text"
    assert content["extract"]["question_text"] == "Why?"
    assert content["summarize"]["summary"] == "short version"


def test_file_hitl_per_record_review_in_namespace():
    """Per-record review fields go under the action namespace, not flat."""
    pipeline, context = _make_hitl_pipeline_and_context()

    input_data = [
        {"source_guid": "sg-1", "content": {"source": {"a": 1}}},
        {"source_guid": "sg-2", "content": {"source": {"a": 2}}},
    ]

    decision = {
        "hitl_status": "approved",
        "record_reviews": [
            {"hitl_status": "approved", "user_comment": "Good"},
            {"hitl_status": "rejected", "user_comment": "Bad"},
        ],
    }

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([decision], True),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    result = results[0]
    # Per-record review overrides file-level decision within the namespace
    ns0 = result.data[0]["content"]["review_answers"]
    assert ns0["hitl_status"] == "approved"
    assert ns0["user_comment"] == "Good"

    ns1 = result.data[1]["content"]["review_answers"]
    assert ns1["hitl_status"] == "rejected"
    assert ns1["user_comment"] == "Bad"


def test_file_hitl_carries_framework_fields():
    """Framework fields (source_guid, target_id, _unprocessed) are preserved from input."""
    pipeline, context = _make_hitl_pipeline_and_context()

    input_data = [
        {
            "source_guid": "sg-1",
            "target_id": "tid-1",
            "_unprocessed": True,
            "_recovery": {"reason": "tombstone"},
            "content": {"source": {"a": 1}},
        },
    ]

    decision = {"hitl_status": "approved"}

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([decision], True),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    item = results[0].data[0]
    assert item["source_guid"] == "sg-1"
    assert item["target_id"] == "tid-1"
    assert item["_unprocessed"] is True
    assert item["_recovery"] == {"reason": "tombstone"}


def test_file_tool_version_merge_spreads_not_wraps():
    """Version merge tool output is spread flat, not wrapped under action name."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config={
                "kind": "tool",
                "granularity": "file",
                "version_consumption_config": {"source": "extract", "pattern": "merge"},
            },
            action_name="aggregate",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config=pipeline.config.action_config,
        agent_name="aggregate",
    )

    input_data = [
        {
            "source_guid": "sg-1",
            "node_id": "n1",
            "content": {
                "extract_1": {"vote": "keep"},
                "extract_2": {"vote": "drop"},
            },
        }
    ]

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=([{"consensus": "keep", "score": 11, "node_id": "n1"}], True),
    ):
        results = pipeline._process_file_mode_tool(input_data, input_data, context)

    content = results[0].data[0]["content"]
    # Flat spread, NOT wrapped under action name
    assert "aggregate" not in content
    assert content["consensus"] == "keep"
    assert content["score"] == 11
    # Existing version namespaces preserved
    assert content["extract_1"]["vote"] == "keep"
    assert content["extract_2"]["vote"] == "drop"

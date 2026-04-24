"""Tests for version merge content format — spread instead of double-nesting.

Version consumption actions receive records whose content is already
namespaced by the version correlator: {v1: {fields}, v2: {fields}}.
The pipeline writer must spread version namespaces directly instead
of wrapping them under the consuming action's name.
"""

from unittest.mock import patch

import pytest

from agent_actions.input.preprocessing.transformation.transformer import (
    DataTransformer,
)
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_version_merge_pipeline_and_context():
    """Create pipeline and context for a version consumption FILE-mode tool."""
    config = {
        "kind": "tool",
        "granularity": "file",
        "version_consumption_config": {
            "source": "filter_learning_quality",
            "pattern": "merge",
        },
    }
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config=config,
            action_name="aggregate_votes",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(agent_config=config, agent_name="aggregate_votes")
    return pipeline, context


def _make_normal_pipeline_and_context():
    """Create pipeline and context for a normal (non-version-merge) FILE-mode tool."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config={"kind": "tool", "granularity": "file"},
            action_name="summarize",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name="summarize",
    )
    return pipeline, context


# ---------------------------------------------------------------------------
# FILE mode: pipeline_file_mode.py
# ---------------------------------------------------------------------------


class TestFileModePipelineVersionMerge:
    """Version merge FILE mode: spread instead of wrap."""

    def test_version_merge_spreads_tool_output(self):
        """Version merge action: tool output spread at top level, not wrapped."""
        pipeline, context = _make_version_merge_pipeline_and_context()

        # Version-correlated input record (what the version correlator produces)
        input_data = [
            {
                "source_guid": "sg-1",
                "node_id": "n1",
                "content": {
                    "filter_learning_quality_1": {"vote": "keep", "score": 8},
                    "filter_learning_quality_2": {"vote": "drop", "score": 3},
                },
            }
        ]

        # Tool returns aggregated output
        tool_output = [{"consensus": "keep", "total_score": 11, "node_id": "n1"}]

        with patch(
            "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
            return_value=(tool_output, True),
        ):
            results = pipeline._process_file_mode_tool(input_data, input_data, context)

        assert results[0].status == ProcessingStatus.SUCCESS
        content = results[0].data[0]["content"]

        # Version namespaces at top level (from existing)
        assert "filter_learning_quality_1" in content
        assert "filter_learning_quality_2" in content
        assert content["filter_learning_quality_1"]["vote"] == "keep"
        assert content["filter_learning_quality_2"]["vote"] == "drop"

        # Tool output spread at top level — NOT wrapped under action name
        assert "aggregate_votes" not in content
        assert content["consensus"] == "keep"
        assert content["total_score"] == 11

    def test_version_merge_preserves_version_namespaces(self):
        """Version namespaces from input are preserved in the output content."""
        pipeline, context = _make_version_merge_pipeline_and_context()

        input_data = [
            {
                "source_guid": "sg-1",
                "node_id": "n1",
                "content": {
                    "filter_learning_quality_1": {"vote": "keep", "score": 8},
                    "filter_learning_quality_2": {"vote": "drop", "score": 3},
                    "filter_learning_quality_3": {"vote": "keep", "score": 7},
                },
            }
        ]

        tool_output = [{"summary": "2/3 keep", "node_id": "n1"}]

        with patch(
            "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
            return_value=(tool_output, True),
        ):
            results = pipeline._process_file_mode_tool(input_data, input_data, context)

        content = results[0].data[0]["content"]
        assert len([k for k in content if k.startswith("filter_learning_quality")]) == 3
        assert content["summary"] == "2/3 keep"

    def test_normal_action_still_wraps_under_action_name(self):
        """Non-version-merge action: tool output wrapped under action name."""
        pipeline, context = _make_normal_pipeline_and_context()

        input_data = [
            {
                "source_guid": "sg-1",
                "node_id": "n1",
                "content": {"upstream_action": {"text": "hello"}},
            }
        ]

        tool_output = [{"summary": "world", "node_id": "n1"}]

        with patch(
            "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
            return_value=(tool_output, True),
        ):
            results = pipeline._process_file_mode_tool(input_data, input_data, context)

        content = results[0].data[0]["content"]
        # Normal action wraps under action name
        assert "summarize" in content
        assert content["summarize"]["summary"] == "world"
        # Existing namespace preserved
        assert "upstream_action" in content

    def test_version_merge_tool_returns_content_key(self):
        """Version merge tool returning {"content": {...}} is handled correctly."""
        pipeline, context = _make_version_merge_pipeline_and_context()

        input_data = [
            {
                "source_guid": "sg-1",
                "node_id": "n1",
                "content": {
                    "filter_learning_quality_1": {"vote": "keep"},
                    "filter_learning_quality_2": {"vote": "drop"},
                },
            }
        ]

        # Tool returns output nested under "content" key
        tool_output = [{"content": {"consensus": "keep"}, "node_id": "n1"}]

        with patch(
            "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
            return_value=(tool_output, True),
        ):
            results = pipeline._process_file_mode_tool(input_data, input_data, context)

        content = results[0].data[0]["content"]
        assert "aggregate_votes" not in content
        assert content["consensus"] == "keep"
        assert content["filter_learning_quality_1"]["vote"] == "keep"


# ---------------------------------------------------------------------------
# LLM path: transformer.py
# ---------------------------------------------------------------------------


class TestTransformStructureVersionMerge:
    """transform_structure with version_merge parameter."""

    def test_version_merge_skips_wrapping(self):
        """version_merge=True: content used directly, not wrapped."""
        data = [{"sg-1": {"consensus": "keep", "total_score": 18}}]

        result = DataTransformer.transform_structure(data, "aggregate_votes", version_merge=True)

        assert len(result) == 1
        assert result[0]["source_guid"] == "sg-1"
        content = result[0]["content"]
        assert "aggregate_votes" not in content
        assert content["consensus"] == "keep"
        assert content["total_score"] == 18

    def test_normal_wraps_under_action_name(self):
        """version_merge=False (default): content wrapped under action name."""
        data = [{"sg-1": {"consensus": "keep"}}]

        result = DataTransformer.transform_structure(data, "aggregate_votes")

        content = result[0]["content"]
        assert "aggregate_votes" in content
        assert content["aggregate_votes"]["consensus"] == "keep"

    def test_version_merge_list_contents(self):
        """version_merge=True with list contents: each item used directly."""
        data = [
            {
                "sg-1": [
                    {"consensus": "keep"},
                    {"consensus": "drop"},
                ]
            }
        ]

        result = DataTransformer.transform_structure(data, "aggregate_votes", version_merge=True)

        assert len(result) == 2
        assert result[0]["content"] == {"consensus": "keep"}
        assert result[1]["content"] == {"consensus": "drop"}
        assert all(r["source_guid"] == "sg-1" for r in result)

    def test_version_merge_empty_action_name_allowed(self):
        """version_merge=True allows empty action_name."""
        data = [{"sg-1": {"consensus": "keep"}}]

        result = DataTransformer.transform_structure(data, "", version_merge=True)

        assert result[0]["content"]["consensus"] == "keep"

    def test_empty_action_name_raises_without_version_merge(self):
        """Empty action_name raises ValueError when version_merge is False."""
        with pytest.raises(ValueError, match="action_name is required"):
            DataTransformer.transform_structure([{"sg-1": {"x": 1}}], "")

    def test_version_merge_non_dict_passthrough(self):
        """version_merge=True with non-dict contents passes them through."""
        data = [{"sg-1": "raw_string_value"}]

        result = DataTransformer.transform_structure(data, "action", version_merge=True)

        assert result[0]["content"] == "raw_string_value"

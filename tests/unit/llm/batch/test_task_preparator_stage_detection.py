"""Tests for batch preparation first-stage detection."""

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator


def test_preparation_context_marks_first_stage_without_dependencies():
    preparator = BatchTaskPreparator(action_indices={"extract": 0, "transform": 1})
    context = preparator._build_preparation_context(
        agent_config={"agent_type": "extract", "prompt": "x"},
        output_directory=None,
        batch_name=None,
        source_data=None,
        workflow_metadata=None,
        tools_path=None,
    )

    assert context.is_first_stage is True


def test_preparation_context_marks_subsequent_stage_with_dependencies():
    preparator = BatchTaskPreparator(action_indices={"extract": 0, "transform": 1})
    context = preparator._build_preparation_context(
        agent_config={"agent_type": "transform", "prompt": "x", "depends_on": ["extract"]},
        output_directory=None,
        batch_name=None,
        source_data=None,
        workflow_metadata=None,
        tools_path=None,
    )

    assert context.is_first_stage is False


def test_preparation_context_uses_index_fallback_when_depends_on_missing():
    preparator = BatchTaskPreparator(action_indices={"extract": 0, "transform": 1})
    context = preparator._build_preparation_context(
        agent_config={"agent_type": "transform", "prompt": "x"},
        output_directory=None,
        batch_name=None,
        source_data=None,
        workflow_metadata=None,
        tools_path=None,
    )

    assert context.is_first_stage is False

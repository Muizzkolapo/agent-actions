"""Parity: FILE-mode empty-output must honor on_empty=warn|error|skip.

The workflow config schema declares ``on_empty: Literal["warn", "error",
"skip"]`` on every action (agent_actions/config/schema.py). The online-LLM
strategy honors all three (agent_actions/processing/strategies/online_llm.py).
The FILE-mode strategy today ignores the field and hard-codes the ``warn``
semantic — ``on_empty=error`` does not abort, ``on_empty=skip`` does not
produce an ``empty_output`` tombstone. These tests pin the intended parity.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_actions.errors.processing import EmptyOutputError
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.record.reasons import EMPTY_OUTPUT


def _make_context(on_empty: str, agent_name: str = "my_file_tool") -> ProcessingContext:
    return ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file", "on_empty": on_empty},
        agent_name=agent_name,
    )


def _empty_response_patch():
    return patch(
        "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
        return_value=([], True),
    )


def test_on_empty_error_raises_empty_output_error():
    context = _make_context("error")
    input_data = [
        {"source_guid": "sg-1", "content": {"prev": {"id": 1}}},
        {"source_guid": "sg-2", "content": {"prev": {"id": 2}}},
    ]
    context.source_data = input_data

    with _empty_response_patch(), pytest.raises(EmptyOutputError) as exc_info:
        FileToolStrategy().invoke(input_data, context)

    assert "my_file_tool" in str(exc_info.value)
    assert "on_empty=error" in str(exc_info.value)


def test_on_empty_skip_produces_empty_output_tombstones():
    context = _make_context("skip")
    input_data = [
        {"source_guid": "sg-1", "content": {"prev": {"id": 1}}},
        {"source_guid": "sg-2", "content": {"prev": {"id": 2}}},
    ]
    context.source_data = input_data

    with _empty_response_patch():
        results = FileToolStrategy().invoke(input_data, context)

    assert len(results) == 2
    for i, result in enumerate(results):
        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == EMPTY_OUTPUT
        assert result.source_guid == input_data[i]["source_guid"]
        assert len(result.data) == 1
        assert result.data[0].get("_state") is not None  # tombstone was built


def test_on_empty_warn_matches_prior_behavior():
    """The default 'warn' branch must be byte-identical to today's behavior."""
    context = _make_context("warn")
    input_data = [
        {"source_guid": "sg-1", "content": {"prev": {"id": 1}}},
        {"source_guid": "sg-2", "content": {"prev": {"id": 2}}},
    ]
    context.source_data = input_data

    with _empty_response_patch():
        results = FileToolStrategy().invoke(input_data, context)

    assert len(results) == 2
    for i, result in enumerate(results):
        assert result.status == ProcessingStatus.FAILED
        assert "returned empty result" in result.error
        assert "2 input record(s)" in result.error
        assert result.source_guid == input_data[i]["source_guid"]


def test_on_empty_default_is_warn_when_unset():
    """Omitting on_empty (agent_config lacks the key) must equal on_empty=warn."""
    context = ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name="my_file_tool",
    )
    input_data = [{"source_guid": "sg-1", "content": {"prev": {"id": 1}}}]
    context.source_data = input_data

    with _empty_response_patch():
        results = FileToolStrategy().invoke(input_data, context)

    assert len(results) == 1
    assert results[0].status == ProcessingStatus.FAILED
    assert "returned empty result" in results[0].error

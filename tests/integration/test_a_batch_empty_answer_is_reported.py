"""What a batch says about an empty answer: the reason on the record and the event."""

from __future__ import annotations

import pytest

from agent_actions.llm.batch.processing import batch_result_strategy
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.logging.events.data_pipeline_events import RecordEmptyOutputEvent
from tests.integration.test_batch_content_materialization import (  # noqa: F401
    action_config,
    context_map,
    upstream_record,
)


def _process(config, context_map, content):  # noqa: F811
    return BatchResultStrategy().process(
        batch_results=[BatchResult(custom_id="tid_001", content=content, success=True, error=None)],
        context_map=context_map,
        output_directory="/tmp/test",
        agent_config=config,
    )


@pytest.mark.parametrize("tool", [{"kind": "tool"}, {"model_vendor": "tool"}])
def test_a_tool_s_empty_answer_is_not_blamed_on_the_model(action_config, context_map, tool):  # noqa: F811
    (result,) = _process({**action_config, **tool}, context_map, [])

    assert result.error.startswith("Tool 'verify_answer' returned an empty list of records")


@pytest.mark.parametrize("on_empty", ["warn", "skip", "error"])
def test_each_empty_answer_fires_one_event_saying_what_was_done(
    action_config,  # noqa: F811
    context_map,  # noqa: F811
    monkeypatch,
    on_empty,
):
    fired = []
    monkeypatch.setattr(batch_result_strategy, "fire_event", fired.append)

    _process({**action_config, "on_empty": on_empty}, context_map, {})

    (event,) = [e for e in fired if isinstance(e, RecordEmptyOutputEvent)]
    assert (event.action_name, event.on_empty) == ("verify_answer", on_empty)
    assert event.source_guid == context_map["tid_001"]["source_guid"]


def test_an_answer_that_is_not_empty_fires_none(action_config, context_map, monkeypatch):  # noqa: F811
    fired = []
    monkeypatch.setattr(batch_result_strategy, "fire_event", fired.append)

    _process(action_config, context_map, {"verified_answer": "C"})

    assert [e for e in fired if isinstance(e, RecordEmptyOutputEvent)] == []

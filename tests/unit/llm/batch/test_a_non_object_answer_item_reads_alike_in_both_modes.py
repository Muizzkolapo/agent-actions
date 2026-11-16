"""A JSON answer whose items are not objects is stored the same way in both modes.

A model can answer a JSON action with `["a", "b"]`, or with prose that json_repair turns into a
list of strings. Online, each item becomes a record holding `{"value": item}`. Batch emptied each
item to `{}` and stored the records as successes with no content.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.helpers import transform_with_passthrough
from agent_actions.processing.types import ProcessingStatus

ACTION = "tag_page"
GUID = "src-1"
ROW: dict[str, Any] = {"source_guid": GUID, "content": {"source": {"page": "p1"}}}
CONFIG: dict[str, Any] = {"action_name": ACTION, "dependencies": ["upstream"]}


def _online(answer: list[Any]) -> list[dict[str, Any]]:
    records = transform_with_passthrough(
        answer,
        {},
        GUID,
        CONFIG,
        action_name=ACTION,
        existing_content=ROW["content"],
        input_record=ROW,
    )
    return [record["content"][ACTION] for record in records]


def _batch(answer: list[Any]) -> list[dict[str, Any]]:
    (result,) = BatchResultStrategy().process(
        [BatchResult(custom_id="r1", content=answer, success=True)],
        context_map={"r1": ROW},
        agent_config=CONFIG,
    )
    assert result.status is ProcessingStatus.SUCCESS
    return [record["content"][ACTION] for record in result.data]


@pytest.mark.parametrize(
    "answer",
    [["a", "b"], [1, 2.5], ["a", {"tag": "b"}], [["nested"]]],
    ids=["strings", "numbers", "mixed", "list"],
)
def test_each_item_is_stored_as_online_stores_it(answer):
    assert _batch(answer) == _online(answer)


def test_a_string_item_is_kept_under_value():
    assert _batch(["a", "b"]) == [{"value": "a"}, {"value": "b"}]

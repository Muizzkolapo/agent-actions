"""The same answer and `context_scope.passthrough` give the same stored record in both modes.

Each case runs one record's answer through online's transform and through the batch result
writer, with the passthrough fields the shared preparation resolved for that record.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.helpers import transform_with_passthrough
from agent_actions.processing.types import ProcessingStatus
from agent_actions.prompt.context.scope_application import apply_context_scope

ACTION = "summarize"
GUID = "src-1"
ROW: dict[str, Any] = {
    "source_guid": GUID,
    "target_id": "r1",
    "content": {
        "source": {"page": "p1"},
        "extract": {"body": "the body", "title": "the title"},
        "empty": {},
    },
}
ANSWER = {"summary": "short"}
# An answer whose own fields are named like a stored record's.
RECORD_SHAPED = {"source_guid": "the model's", "content": {"summary": "short"}, "note": "n"}

SCOPES: dict[str, dict[str, list[str]]] = {
    "none": {},
    "one field": {"passthrough": ["extract.title"]},
    "a whole namespace": {"passthrough": ["extract.*"]},
    "an empty namespace": {"passthrough": ["empty.*"]},
    "a field dropped again": {"passthrough": ["extract.title"], "drop": ["extract.title"]},
    "a dropped field named like a namespace": {
        "passthrough": ["extract.source"],
        "drop": ["extract.source"],
    },
}


def _config(scope: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "action_name": ACTION,
        "dependencies": ["extract"],
        "context_scope": {"observe": ["extract.body"], **scope},
    }


def _passthrough_fields(config: dict[str, Any]) -> dict[str, Any]:
    _, _, fields = apply_context_scope(
        ROW["content"], config["context_scope"], action_name=ACTION, report_inert_drops=False
    )
    return fields


def _stored(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # node_id is assigned to both by the enrichment that follows; online's transform
    # also mints a placeholder.
    return [{k: v for k, v in record.items() if k != "node_id"} for record in records]


def _online(answer: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """As `OnlineLLMStrategy` transforms a response, then carries the record's target_id."""
    records = transform_with_passthrough(
        [answer],
        ROW["content"],
        GUID,
        config,
        action_name=ACTION,
        passthrough_fields=_passthrough_fields(config),
        existing_content=ROW["content"],
        input_record=ROW,
    )
    return _stored([{**record, "target_id": ROW["target_id"]} for record in records])


def _batch(answer: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    row = dict(ROW)
    BatchContextMetadata.set_passthrough_fields(row, _passthrough_fields(config))
    (result,) = BatchResultStrategy().process(
        [BatchResult(custom_id="r1", content=answer, success=True)],
        context_map={"r1": row},
        agent_config=config,
    )
    assert result.status is ProcessingStatus.SUCCESS
    return _stored(result.data)


@pytest.mark.parametrize("scope", SCOPES.values(), ids=SCOPES.keys())
@pytest.mark.parametrize("answer", [ANSWER, RECORD_SHAPED], ids=["plain", "record-shaped"])
def test_the_stored_record_is_the_one_online_stores(answer, scope):
    config = _config(scope)
    assert _batch(answer, config) == _online(answer, config)


def test_one_field_is_stored_beside_the_action_namespace():
    """Pinned outright, so agreeing on a wrong record cannot pass the parity test."""
    (record,) = _batch(ANSWER, _config(SCOPES["one field"]))
    assert record["content"][ACTION] == ANSWER
    assert record["content"]["extract"] == ROW["content"]["extract"]


def test_a_passthrough_that_resolves_to_nothing_adds_nothing():
    for name in ("an empty namespace", "a field dropped again"):
        (record,) = _batch(ANSWER, _config(SCOPES[name]))
        assert record["content"] == {**ROW["content"], ACTION: ANSWER}, name

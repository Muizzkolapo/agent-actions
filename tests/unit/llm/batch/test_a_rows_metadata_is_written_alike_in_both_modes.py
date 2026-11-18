"""A stored row's `metadata` holds the same keys online and in batch, none read from the answer.

Online read it from the model's parsed answer: under `expect:` one record arrives as a dict,
so a schema field named `id`, `model`, `finish_reason` or `usage` became the row's
`request_id`, model, stop reason or token counts. Batch wrote the vendor's own dict, with
other keys for each vendor and no `provider`.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.processing.enrichment import MetadataEnricher
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from tests.unit.llm.batch.one_answer_both_paths import (
    CONFIG,
    CONTEXT_MAP,
    anthropic_message,
    batch_result,
    chat_completion,
    gemini_response,
    ollama_response,
    online_answer,
)

ANSWER = (
    '{"id": "42", "model": "tide table", "finish_reason": "done", "usage": {"total_tokens": 1}}'
)

# vendor: a response that answers ANSWER, and the reason it gives for stopping
ANSWERED: dict[str, tuple[dict[str, Any], str]] = {
    "openai": (chat_completion(ANSWER), "stop"),
    "groq": (chat_completion(ANSWER), "stop"),
    "gemini": (gemini_response([{"text": ANSWER}]), "STOP"),
    "anthropic": (anthropic_message([{"type": "text", "text": ANSWER}]), "end_turn"),
    "ollama_local": (ollama_response(ANSWER), "stop"),
}


def _config(vendor: str) -> dict[str, Any]:
    return {**CONFIG, "model_vendor": vendor}


def _enriched(result: ProcessingResult, config: dict[str, Any]) -> dict[str, Any]:
    context = result.processing_context or ProcessingContext(
        agent_config=config,  # type: ignore[arg-type]
        agent_name="act",
    )
    (row,) = MetadataEnricher().enrich(result, context).data
    return dict(row["metadata"])


def _online_metadata(vendor: str) -> dict[str, Any]:
    """The metadata of the row online stores for the answer, which arrives as one dict."""
    (answer,) = online_answer(vendor, ANSWERED[vendor][0], json_mode=True)
    result = ProcessingResult.success(data=[{"content": {"act": answer}}], raw_response=answer)
    return _enriched(result, _config(vendor))


def _batch_metadata(vendor: str) -> dict[str, Any]:
    (result,) = BatchResultStrategy().process(
        [batch_result(vendor, ANSWERED[vendor][0], json_mode=True)],
        context_map=CONTEXT_MAP,
        agent_config=_config(vendor),
    )
    return _enriched(result, _config(vendor))


@pytest.mark.parametrize("vendor", sorted(ANSWERED))
def test_no_field_of_the_answer_is_read_as_metadata(vendor):
    metadata = _online_metadata(vendor)

    assert set(metadata) == {"model", "provider"}
    assert metadata["model"] == CONFIG["model_name"]


@pytest.mark.parametrize("vendor", sorted(ANSWERED))
def test_batch_writes_the_keys_online_writes_and_the_stop_reason_it_knows(vendor):
    _, stop_reason = ANSWERED[vendor]

    assert _batch_metadata(vendor) == {**_online_metadata(vendor), "finish_reason": stop_reason}


def test_a_failed_batch_row_keeps_the_stop_reason_alone_of_the_vendors_metadata():
    filtered = batch_result("openai", chat_completion(None, "content_filter"), json_mode=False)

    (result,) = BatchResultStrategy().process(
        [filtered], context_map=CONTEXT_MAP, agent_config=_config("openai")
    )

    (row,) = result.data
    assert set(row["metadata"]) == {"reason", "agent_type", "finish_reason"}
    assert row["metadata"]["finish_reason"] == "content_filter"

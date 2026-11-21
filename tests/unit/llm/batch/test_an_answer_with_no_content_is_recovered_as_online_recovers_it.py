"""A batch resends or regenerates an answer with no content exactly when online does.

Online never calls again for a refusal: in JSON mode it is a `_parse_error` record, in text
mode an error its retry policy does not retry. A batch `retry:` resent it until its attempts
were spent. Under `expect:` with a repair policy, online regenerates that `_parse_error`
record when the schema or a rule rejects it; batch held any result with no content to be a
provider failure and never regenerated it.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import ProcessingStatus
from tests.unit.llm.batch.one_answer_both_paths import (
    RECORD_ID,
    CollectPass,
    anthropic_message,
    batch_line,
    chat_completion,
    gemini_response,
    online_answer,
)

ACTION = "label_page"
PROMPT = "Label the page."
REFUSAL = "I can't help with that request."
REFUSED = f"The model refused to answer: {REFUSAL}"
SCHEMA = {
    "type": "object",
    "properties": {"topic": {"type": "string"}},
    "required": ["topic"],
}
GOOD = {"topic": "tides"}

# vendor, a response that holds no answer
UNANSWERED: dict[str, tuple[str, dict[str, Any]]] = {
    "openai refusal": ("openai", chat_completion(None, refusal=REFUSAL)),
    "groq no content": ("groq", chat_completion(None)),
    "gemini blocked prompt": ("gemini", gemini_response(None, block_reason="SAFETY")),
    "anthropic no blocks": ("anthropic", anthropic_message([])),
    "anthropic thinking only": (
        "anthropic",
        anthropic_message([{"type": "thinking", "thinking": "hm", "signature": "s"}]),
    ),
}


def _config(*, json_mode: bool, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "llm",
        "name": ACTION,
        "action_name": ACTION,
        "agent_type": ACTION,
        "model_name": "m",
        "json_mode": json_mode,
        "prompt": PROMPT,
        "run_mode": "batch",
        **extra,
    }


def _retrying(json_mode: bool) -> dict[str, Any]:
    return _config(json_mode=json_mode, retry={"enabled": True, "max_attempts": 3})


# ---------------------------------------------------------------------------
# retry:
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("case", sorted(UNANSWERED))
def test_an_answer_with_no_content_is_not_resent(case, json_mode):
    vendor, body = UNANSWERED[case]

    done = CollectPass([batch_line(vendor, body)], _retrying(json_mode)).run()

    assert done.resent == []
    assert not done.exhausted


def test_a_refusal_in_text_mode_fails_with_what_online_raises():
    body = chat_completion(None, refusal=REFUSAL)
    with pytest.raises(Exception) as raised:
        online_answer("openai", body, json_mode=False)

    result = CollectPass([batch_line("openai", body)], _retrying(False)).run().processed()

    assert result.status is ProcessingStatus.FAILED
    assert result.error == str(raised.value) == REFUSED


def test_a_refusal_in_json_mode_is_stored_as_online_stores_it():
    body = chat_completion(None, refusal=REFUSAL)
    (online_record,) = online_answer("openai", body, json_mode=True)

    result = CollectPass([batch_line("openai", body)], _retrying(True)).run().processed()

    (row,) = result.data
    assert row["content"][ACTION] == online_record == {"raw_response": "", "_parse_error": REFUSED}


def test_text_cut_off_before_it_began_is_still_resent():
    """Online raises a ResponseTruncatedError here, which its retry policy retries."""
    line = batch_line("openai", chat_completion(None, "length"))

    done = CollectPass([line], _retrying(False)).run()

    assert done.resent == [{RECORD_ID}]


# ---------------------------------------------------------------------------
# expect: with a repair policy
# ---------------------------------------------------------------------------


def _expecting(json_mode: bool = True, **expect: Any) -> dict[str, Any]:
    return _config(json_mode=json_mode, schema=SCHEMA, expect={"repair": "auto", **expect})


def _online_prompts(vendor: str, body: dict[str, Any], config: dict[str, Any]) -> list[str]:
    """Every prompt online sends: the first answer is *body*, any regeneration answers well."""
    service = create_expectation_service_from_config(
        config["expect"], action_name=ACTION, agent_config=config
    )
    assert service is not None
    prompts: list[str] = []

    def call(prompt: str) -> tuple[Any, bool]:
        prompts.append(prompt)
        if len(prompts) == 1:
            return online_answer(vendor, body, json_mode=config["json_mode"]), True
        return [GOOD], True

    service.execute(call, PROMPT)
    return prompts


def _batch_repair_prompts(vendor: str, body: dict[str, Any], config: dict[str, Any]) -> list[str]:
    """The prompt each record a batch sends to repair is regenerated with."""
    done = CollectPass([batch_line(vendor, body)], config).run()
    return [
        feedback(PROMPT) if callable(feedback) else f"{PROMPT}\n\n{feedback}".rstrip()
        for _, feedback in done.repaired
    ]


@pytest.mark.parametrize(
    "expect",
    [{}, {"structural": "auto"}, {"structural": {"prompt": "{original_prompt}\nAnswer in JSON."}}],
    ids=["structural retry", "structural auto", "structural template"],
)
@pytest.mark.parametrize("case", sorted(UNANSWERED))
def test_an_answer_with_no_content_is_regenerated_with_the_prompt_online_sends(case, expect):
    vendor, body = UNANSWERED[case]
    config = _expecting(**expect)

    online = _online_prompts(vendor, body, config)

    assert len(online) == 2, "online regenerates a parse-error record the schema rejects"
    assert _batch_repair_prompts(vendor, body, config) == online[1:]


def test_a_parse_error_record_the_suite_accepts_is_regenerated_in_neither_mode():
    """With no schema to reject it and a rule it passes, online keeps the record."""
    config = _config(
        json_mode=True,
        expect={
            "repair": "auto",
            "expectations": [{"id": "said_why", "type": "not_null", "field": "_parse_error"}],
        },
    )
    vendor, body = UNANSWERED["openai refusal"]

    assert len(_online_prompts(vendor, body, config)) == 1
    assert _batch_repair_prompts(vendor, body, config) == []


def test_a_refusal_in_text_mode_is_not_regenerated():
    """Online raises it before any expectation runs."""
    vendor, body = UNANSWERED["openai refusal"]
    config = _expecting(json_mode=False)

    done = CollectPass([batch_line(vendor, body)], config).run()

    assert done.repaired == []
    assert done.processed().error == REFUSED


@pytest.mark.parametrize(
    "failure",
    [
        BatchResult(RECORD_ID, None, False, error="HTTP 500: overloaded", error_status=500),
        BatchResult(RECORD_ID, None, False, error="Batch result expired before processing"),
    ],
    ids=["http error", "expired"],
)
def test_a_request_that_failed_is_still_not_regenerated(failure):
    done = CollectPass([failure], _expecting()).run()

    assert done.repaired == []
    assert done.processed().status is ProcessingStatus.FAILED

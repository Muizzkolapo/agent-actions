"""A `json_mode: false` action gets its batch answer as text under `output_field`, as online does.

The batch clients parse every text answer as JSON. A plain-text action whose answer is JSON text
(a writer that prints a JSON object) became that object, and one whose answer is plain text stayed
a bare string. The expectation loop checks the content against the action's schema before
anything wrapped it, so both failed every repair round: `{questions: ...}` and `"Q1: PASS"` are not
`{raw: ...}` or `{verdicts: ...}`. Online, `call_non_json` wraps the text first (`wrap_non_json`).
"""

from __future__ import annotations

import json
from typing import Any

from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.batch_base import BatchResult

JSON_TEXT = '{"questions": [{"stem": "Which flag?"}]}'
PLAIN_TEXT = "Q1: PASS | difficulty 3"


def _anthropic_line(text: str) -> dict[str, Any]:
    """One line of an Anthropic batch result file: a thinking block, then the text."""
    return {
        "custom_id": "r1",
        "result": {
            "type": "succeeded",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "...", "signature": "sig"},
                    {"type": "text", "text": text},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        },
    }


def _client() -> AnthropicBatchClient:
    return AnthropicBatchClient(api_key="sk-ant-test")


class _Provider:
    """A provider whose results are the parsed Anthropic lines."""

    def __init__(self, *texts: str) -> None:
        self._results = [_client().parse_provider_response(_anthropic_line(t)) for t in texts]

    def retrieve_results(self, batch_id: str, output_directory: str | None) -> list[BatchResult]:
        return self._results


class TestTheParsedResultKeepsTheText:
    def test_json_text_keeps_its_original_text(self):
        result = _client().parse_provider_response(_anthropic_line(JSON_TEXT))

        assert result.raw_text == JSON_TEXT

    def test_plain_text_keeps_its_original_text(self):
        result = _client().parse_provider_response(_anthropic_line(PLAIN_TEXT))

        assert result.raw_text == PLAIN_TEXT


class TestAPlainTextActionGetsTheTextUnderItsOutputField:
    def test_json_text_is_kept_as_text(self):
        (result,) = retrieve_and_reconcile(
            _Provider(JSON_TEXT),
            "b1",
            None,
            agent_config={"json_mode": False, "output_field": "raw"},
        )

        assert result.content == {"raw": JSON_TEXT}

    def test_plain_text_is_wrapped(self):
        (result,) = retrieve_and_reconcile(
            _Provider(PLAIN_TEXT),
            "b1",
            None,
            agent_config={"json_mode": False, "output_field": "verdicts"},
        )

        assert result.content == {"verdicts": PLAIN_TEXT}

    def test_the_default_output_field_is_used_when_none_is_set(self):
        (result,) = retrieve_and_reconcile(
            _Provider(PLAIN_TEXT), "b1", None, agent_config={"json_mode": False}
        )

        assert result.content == {"raw_response": PLAIN_TEXT}


class TestAnAnswerWithNoTextIsNotWrapped:
    def test_a_thinking_only_answer_has_no_text(self):
        line = _anthropic_line("x")
        line["result"]["message"]["content"] = [
            {"type": "thinking", "thinking": "...", "signature": "s"}
        ]
        line["result"]["message"]["stop_reason"] = "max_tokens"

        result = _client().parse_provider_response(line)

        assert result.raw_text is None

    def test_a_thinking_only_answer_still_fails_the_schema_shape(self):
        line = _anthropic_line("x")
        line["result"]["message"]["content"] = [
            {"type": "thinking", "thinking": "...", "signature": "s"}
        ]

        class _ThinkingOnly:
            def retrieve_results(self, batch_id, output_directory):
                return [_client().parse_provider_response(line)]

        (result,) = retrieve_and_reconcile(
            _ThinkingOnly(), "b1", None, agent_config={"json_mode": False, "output_field": "raw"}
        )

        assert not (isinstance(result.content, dict) and "raw" in result.content)

    def test_the_text_null_is_kept_as_text(self):
        (result,) = retrieve_and_reconcile(
            _Provider("null"),
            "b1",
            None,
            agent_config={"json_mode": False, "output_field": "verdicts"},
        )

        assert result.content == {"verdicts": "null"}


class TestStructuredContentWithNoTextIsUnchanged:
    def test_an_object_with_no_text_stays_an_object(self):
        given = BatchResult(custom_id="r1", content={"q": "kept"}, success=True)

        class _Objects:
            def retrieve_results(self, batch_id, output_directory):
                return [given]

        (result,) = retrieve_and_reconcile(
            _Objects(), "b1", None, agent_config={"json_mode": False, "output_field": "raw"}
        )

        assert result.content == {"q": "kept"}


class TestAJsonActionIsUnchanged:
    def test_json_mode_keeps_the_parsed_object(self):
        (result,) = retrieve_and_reconcile(
            _Provider(JSON_TEXT), "b1", None, agent_config={"json_mode": True}
        )

        assert result.content == json.loads(JSON_TEXT)

    def test_no_config_keeps_the_parsed_object(self):
        (result,) = retrieve_and_reconcile(_Provider(JSON_TEXT), "b1", None)

        assert result.content == json.loads(JSON_TEXT)

    def test_a_failed_result_is_unchanged(self):
        failed = BatchResult(custom_id="r1", content=None, success=False, error="overloaded")

        class _Failed:
            def retrieve_results(self, batch_id, output_directory):
                return [failed]

        (result,) = retrieve_and_reconcile(
            _Failed(), "b1", None, agent_config={"json_mode": False, "output_field": "raw"}
        )

        assert result.content is None and result.error == "overloaded"

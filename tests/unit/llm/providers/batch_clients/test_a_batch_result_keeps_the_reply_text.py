"""A batch result keeps the reply as the model wrote it, beside the parsed content (1814).

The judge reads a verdict only from a reply that is wholly one, as online does.
The batch parser is lenient, and would read a verdict out of prose that quotes
one, so the judge tally reads the text, not the content.
"""

from __future__ import annotations

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient

PROSE = 'No. The example {"passed": true, "reason": "x"} does not apply here.'


def _anthropic() -> AnthropicBatchClient:
    client = AnthropicBatchClient.__new__(AnthropicBatchClient)
    client.enable_prompt_caching = False
    return client


def _anthropic_line(content):
    return {
        "custom_id": "r1",
        "result": {
            "type": "succeeded",
            "message": {"content": content, "stop_reason": "end_turn", "usage": {}},
        },
    }


def test_an_openai_shaped_reply_keeps_its_text():
    line = {"custom_id": "r1", "response": {"body": {"choices": [{"message": {"content": PROSE}}]}}}
    result = AgacBatchClient().parse_provider_response(line)
    assert result.text == PROSE
    assert isinstance(result.content, dict), "the content is still parsed for the record"


def test_an_anthropic_text_reply_keeps_its_text():
    result = _anthropic().parse_provider_response(
        _anthropic_line([{"type": "text", "text": PROSE}])
    )
    assert result.text == PROSE


def test_an_anthropic_tool_answer_has_no_text():
    tool = {"type": "tool_use", "name": "answer", "input": {"passed": True}}
    result = _anthropic().parse_provider_response(_anthropic_line([tool]))
    assert result.text is None
    assert result.content == {"passed": True}

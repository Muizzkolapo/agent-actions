"""A Gemini batch line carries its generation settings where and as the API reads them."""

from typing import Any

from google.genai import types

from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.prompt.message_builder import MessageBuilder

ROW = {"target_id": "r1", "content": {"t": "x"}, "prompt": "Summarise"}
SCHEMA = {
    "name": "Summary",
    "schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    },
}
# Fields of GenerateContentRequest a line carries beside generation_config.
REQUEST_FIELDS = {
    "contents",
    "generation_config",
    "safety_settings",
    "system_instruction",
    "tool_config",
    "cached_content",
    "labels",
}


def _request(**config: Any) -> dict[str, Any]:
    client = GeminiBatchClient.__new__(GeminiBatchClient)
    (task,) = client.prepare_tasks([dict(ROW)], {"model_name": "m", **config})
    return task["request"]  # type: ignore[no-any-return]


def _nulls(value: Any, path: str = "") -> list[str]:
    if value is None:
        return [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _nulls(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _nulls(v, f"{path}[{i}]")]
    return []


def test_the_token_limit_is_gemini_s_max_output_tokens():
    generation_config = _request(max_tokens=256)["generation_config"]

    assert generation_config["max_output_tokens"] == 256
    assert types.GenerationConfig.model_validate(generation_config).max_output_tokens == 256


def test_an_unset_limit_writes_no_null():
    request = _request(json_mode=True, compiled_schema=SCHEMA)

    assert "max_output_tokens" not in request["generation_config"]
    assert _nulls(request) == []


def test_json_mode_asks_for_json_inside_the_generation_config():
    request = _request(json_mode=True, compiled_schema=SCHEMA)

    assert set(request) <= REQUEST_FIELDS
    generation_config = types.GenerationConfig.model_validate(request["generation_config"])
    assert generation_config.response_mime_type == "application/json"
    assert generation_config.response_schema is None


def test_the_batch_prompt_carries_the_schema_text_online_sends():
    online = MessageBuilder.build("gemini", "Summarise", {"t": "x"}, schema=SCHEMA, json_mode=True)
    schema_line = next(
        line for line in online.prompt_body.splitlines() if "begin_of_output_schema" in line
    )

    text = _request(json_mode=True, compiled_schema=SCHEMA)["contents"][0]["parts"][0]["text"]

    assert schema_line in text
    for rule in online.rules:
        assert rule in text


def test_a_text_call_gets_no_schema_text_or_json_mime_type():
    request = _request(json_mode=False)

    assert "begin_of_output_schema" not in request["contents"][0]["parts"][0]["text"]
    assert "response_mime_type" not in request.get("generation_config", {})


def test_json_mode_without_a_schema_still_asks_for_json():
    assert (
        _request(json_mode=True)["generation_config"]["response_mime_type"] == "application/json"
    )

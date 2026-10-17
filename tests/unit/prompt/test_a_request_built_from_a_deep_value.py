"""A request is built from a record value nested past the interpreter's recursion limit.

Each step that turns the record into request text gives the text it gave before for an
ordinary value, and the same text, without a depth limit, for a deep one.
"""

import datetime
import json
import math

import pytest

from agent_actions.errors import RecordContextError, TemplateVariableError
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.llm.realtime.services.context import ContextService
from agent_actions.prompt.jinja_env import DictKeyFirstEnvironment
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.utils import deep_json
from agent_actions.utils.json_safety import _convert_without_recursion, ensure_json_safe

DEPTH = 20_000
LEAF = "leaf é"


def _deep(depth: int = DEPTH) -> list:
    node: list = [LEAF]
    for _ in range(depth - 1):
        node = [node]
    return node


def _deep_text(ensure_ascii: bool) -> str:
    return "[" * DEPTH + json.dumps(LEAF, ensure_ascii=ensure_ascii) + "]" * DEPTH


ORDINARY = {
    "source": {
        "b": [1, 2.5, None, True, "é", (1, 2)],
        "a": {"nested": {"x": float("nan")}, 3: "int key"},
        "when": datetime.date(2020, 1, 2),
        "raw": b"bytes",
    }
}


class _Opaque:
    def __str__(self) -> str:
        return "opaque"


def _recursive_reference(obj):
    """``ensure_json_safe`` as it was written before it kept its own stack."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {str(k): _recursive_reference(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_recursive_reference(item) for item in obj]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (set, frozenset)):
        return [_recursive_reference(item) for item in obj]
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    return str(obj)


class TestEnsureJsonSafe:
    def test_an_ordinary_value_converts_as_it_did(self):
        value = {
            **ORDINARY,
            "set": {3},
            "inf": float("-inf"),
            "opaque": _Opaque(),
            "shared": [[1], [1]],
            1: "collides",
            "1": "with this",
        }
        expected = _recursive_reference(value)
        for got in (ensure_json_safe(value), _convert_without_recursion(value)):
            assert got == expected
            assert json.dumps(got) == json.dumps(expected)

    def test_a_deep_value_converts(self):
        assert deep_json.dumps(ensure_json_safe({"d": (_deep(),)}), ensure_ascii=False) == (
            '{"d": [' + _deep_text(False) + "]}"
        )

    def test_a_container_that_holds_itself_is_refused(self):
        loop: list = []
        loop.append(loop)
        with pytest.raises(ValueError, match="Circular reference"):
            ensure_json_safe({"a": loop})


class TestTheOnlineRequest:
    def test_the_context_string_of_an_ordinary_record_is_unchanged(self):
        assert ContextService.prepare_context_data(ORDINARY, is_tool=False) == json.dumps(
            _recursive_reference(ORDINARY), ensure_ascii=False
        )

    def test_the_context_string_of_a_deep_record_holds_the_whole_value(self):
        text = ContextService.prepare_context_data({"source": {"deep": _deep()}}, False)
        assert text == '{"source": {"deep": ' + _deep_text(False) + "}}"

    def test_an_ollama_message_serialises_a_deep_context(self):
        text = MessageBuilder._serialise_context({"deep": _deep()}, "ollama_local")
        assert text == '{"deep": ' + _deep_text(False) + "}"


class TestTheBatchRequest:
    def test_a_task_carries_a_deep_record_and_an_ordinary_one_unchanged(self):
        client = OpenAIBatchClient(api_key="sk-not-used")
        ordinary = {"source": {"page": "é", "n": [1, 2]}}
        tasks = client.prepare_tasks(
            [
                {"target_id": "t0", "content": {"source": {"deep": _deep()}}, "prompt": "p"},
                {"target_id": "t1", "content": ordinary, "prompt": "p"},
            ],
            {"model_name": "gpt-4o-mini", "json_mode": False},
        )
        users = [
            next(m["content"] for m in t["body"]["messages"] if m["role"] == "user") for t in tasks
        ]
        assert users == ['{"source": {"deep": ' + _deep_text(True) + "}}", json.dumps(ordinary)]


class TestThePromptTemplate:
    def test_tojson_renders_an_ordinary_value_as_it_did(self):
        from jinja2 import Environment

        template = "{{ v | tojson }} {{ v | tojson(indent=2) }}"
        value = {"b": [1, "<é>"], "a": None}
        assert DictKeyFirstEnvironment().from_string(template).render(v=value) == (
            Environment().from_string(template).render(v=value)
        )

    def test_tojson_renders_a_deep_value(self):
        rendered = DictKeyFirstEnvironment().from_string("{{ v | tojson }}").render(v=_deep())
        assert rendered == "[" * DEPTH + json.dumps(LEAF) + "]" * DEPTH

    def test_printing_a_deep_value_fails_the_record_naming_the_field_and_the_limit(self):
        with pytest.raises(RecordContextError) as raised:
            PromptPreparationService._render_prompt_template(
                "{{ source.deep }}",
                {"source": {"deep": _deep(), "page": "p"}, "other": {"x": [[1]]}},
                agent_name="summarize",
            )
        message = str(raised.value)
        assert f"cannot render source.deep: it is nested {DEPTH} levels deep" in message
        assert "Python's recursion limit (" in message
        assert "| tojson" in message

    def test_printing_an_ordinary_value_renders_as_it_did(self):
        rendered = PromptPreparationService._render_prompt_template(
            "{{ source.v }}", {"source": {"v": [[1], {"a": "é"}]}}, agent_name="summarize"
        )
        assert rendered == str([[1], {"a": "é"}])

    def test_a_recursion_no_field_explains_fails_as_it_did(self):
        with pytest.raises(TemplateVariableError):
            PromptPreparationService._render_prompt_template(
                "{% macro f() %}{{ f() }}{% endmacro %}{{ f() }}",
                {"source": {"page": [[1]]}},
                agent_name="summarize",
            )

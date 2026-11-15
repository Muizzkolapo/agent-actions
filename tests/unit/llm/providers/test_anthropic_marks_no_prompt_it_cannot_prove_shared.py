"""A prompt the detector cannot prove the same for every record gets no cache mark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from agent_actions.expectations.judge import invoke_judge
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.validation.static_analyzer.workflow_static_analyzer import analyze_workflow

MODEL = "claude-sonnet-4-6"
RECORDS = (
    {"source": {"page_content": "alpha-page", "exam": "dbt"}, "upstream": {"field": "alpha-up"}},
    {"source": {"page_content": "beta-page", "exam": "snow"}, "upstream": {"field": "beta-up"}},
)
SEED = {
    "syl": {
        "select_by": "source.exam",
        "files": {"dbt": "$file:dbt.json", "snow": "$file:snow.json"},
    },
    "rules": "$file:rules.json",
}
SEED_FILES = {
    "dbt.json": {"label": "DBT-LABEL"},
    "snow.json": {"label": "SNOW-LABEL"},
    "rules.json": {"label": "RULES-LABEL"},
}
TOOLS = {
    "label_for.py": (
        "import json\n\n\ndef label_for(context_json):\n"
        "    return json.loads(context_json)['source']['page_content'].upper()\n"
    ),
}


def _marked_texts(value: Any) -> list[str]:
    if isinstance(value, dict):
        own = [value["text"]] if "cache_control" in value else []
        return own + [t for v in value.values() for t in _marked_texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _marked_texts(v)]
    return []


def _transport(sent: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        block = (
            {
                "type": "tool_use",
                "id": "t",
                "name": body["tools"][0]["name"],
                "input": {"topic": "x"},
            }
            if "tools" in body
            else {"type": "text", "text": '{"passed": true, "reason": "ok"}'}
        )
        return httpx.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": MODEL,
                "content": [block],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    return httpx.MockTransport(handler)


def _offline(sent: list[dict[str, Any]]):
    return patch(
        "agent_actions.llm.providers.client_base.get_or_create_client",
        lambda *_a, **_k: anthropic.Anthropic(
            api_key="sk-ant-test", http_client=httpx.Client(transport=_transport(sent))
        ),
    )


def _project(root: Path) -> dict[str, Any]:
    workflow = root / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    for name, content in SEED_FILES.items():
        (workflow / "seed_data" / name).write_text(json.dumps(content))
    (root / "tools").mkdir()
    for name, text in TOOLS.items():
        (root / "tools" / name).write_text(text)
    return {
        "workflow_config_path": str(workflow / "agent_config" / "wf.yml"),
        "tool_path": [str(root / "tools")],
        "_project_root": str(root),
    }


def _config(root: Path, prompt: str, **extra: Any) -> dict[str, Any]:
    return {
        "agent_type": "summarize",
        "action_name": "summarize",
        "name": "summarize",
        "model_vendor": "anthropic",
        "model_name": MODEL,
        "api_key": "TEST_ANTHROPIC_KEY",
        "json_mode": False,
        "granularity": "record",
        "enable_prompt_caching": True,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content", "upstream.field"], "seed": SEED},
        **_project(root),
        **extra,
    }


def _online(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Render each record's prompt and send it online; return each request body."""
    sent: list[dict[str, Any]] = []
    version = config.get("_version_context")
    for record in RECORDS:
        field_context = {**record, "version": version} if version else dict(record)
        prepared = PromptPreparationService.prepare_prompt_with_field_context(
            config, "summarize", record["source"], field_context=field_context
        )
        context = MagicMock()
        context.agent_name = "summarize"
        context.agent_config = config
        task = PreparedTask(
            target_id=record["source"]["page_content"],
            source_guid="sg",
            formatted_prompt=prepared.formatted_prompt,
            llm_context=prepared.llm_context,
        )
        with _offline(sent):
            OnlineStrategy().invoke(task, context)
    return sent


def _prompt_text(body: dict[str, Any]) -> str:
    content = body["messages"][0]["content"]
    text = content if isinstance(content, str) else "".join(b["text"] for b in content)
    return text.split("<|begin_of_text|>")[0]


SCHEMA_WITH_FIELD_DISPATCH = {
    "name": "topic_answer",
    "fields": [{"id": "topic", "type": "string", "description": "dispatch_task('label_for')"}],
}

NO_MARK = {
    "upstream field": ("Summarise {{ upstream.field }}.", {}),
    "seed key chosen per record": ("Rules: {{ seed.syl.label }}.", {}),
    "seed key by constant subscript": ('Rules: {{ seed["syl"].label }}.', {}),
    "seed key by variable subscript": ('{% set k = "syl" %}Rules: {{ seed[k].label }}.', {}),
    "dispatch call in the prompt": ("Topic: dispatch_task('label_for').", {}),
    "source after a loop that binds the name": (
        "{% for source in [1] %}{% endfor %}Summarise {{ source.page_content }}.",
        {},
    ),
    "dispatch inside a schema field": (
        "Summarise the page.",
        {"json_mode": True, "schema": SCHEMA_WITH_FIELD_DISPATCH},
    ),
}

ONE_SHARED_MARK = {
    "seed key with no select_by": ("Rules: {{ seed.rules.label }}.", {}),
    "version namespace": (
        "Version {{ version.i }} of the summary.",
        {"_version_context": {"i": 1}},
    ),
    "inline macro": ("{% macro b(t) %}<{{ t }}>{% endmacro %}Summarise {{ b('static') }}.", {}),
}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-ant-test")


@pytest.mark.parametrize(("prompt", "extra"), NO_MARK.values(), ids=NO_MARK.keys())
def test_a_request_that_differs_per_record_carries_no_mark(tmp_path, prompt, extra):
    first, second = _online(_config(tmp_path, prompt, **extra))

    assert (_prompt_text(first), first.get("tools")) != (_prompt_text(second), second.get("tools"))
    assert [_marked_texts(first), _marked_texts(second)] == [[], []]


@pytest.mark.parametrize(("prompt", "extra"), ONE_SHARED_MARK.values(), ids=ONE_SHARED_MARK.keys())
def test_a_prompt_the_same_for_every_record_keeps_one_shared_mark(tmp_path, prompt, extra):
    first, second = _online(_config(tmp_path, prompt, **extra))

    assert _prompt_text(first) == _prompt_text(second)
    assert len(_marked_texts(first)) == 1
    assert _marked_texts(first) == _marked_texts(second)


class TestJudge:
    def test_a_judge_call_carries_no_mark_for_an_action_with_a_static_prompt(self, tmp_path):
        config = _config(tmp_path, "Summarise the page.")
        own: list[dict[str, Any]] = []
        with _offline(own):
            AnthropicClient.call_non_json(None, config, "Summarise the page.", {"page": "a"})
        judged: list[dict[str, Any]] = []
        with _offline(judged):
            for value in ("alpha-output", "beta-output"):
                invoke_judge(config, "The summary is short.", value, action_name="summarize")

        values = ("alpha-output", "beta-output")
        assert len(_marked_texts(own)) == 1
        assert [v in json.dumps(b) for b, v in zip(judged, values, strict=True)] == [True, True]
        assert [_marked_texts(b) for b in judged] == [[], []]


def _warnings(actions: list[dict[str, Any]]) -> list[str]:
    result = analyze_workflow({"name": "pages", "actions": actions})
    return [w.message for w in result.warnings if "enable_prompt_caching" in w.message]


def _action(prompt: str = "Summarise the page.", **extra: Any) -> dict[str, Any]:
    return {
        "name": "summarize",
        "model_vendor": "anthropic",
        "enable_prompt_caching": True,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content"]},
        "schema": {"summary": "string"},
        **extra,
    }


class TestPreflightWarning:
    def test_another_vendor_gets_no_warning(self):
        assert (
            _warnings([_action("Summarise {{ source.page_content }}.", model_vendor="openai")])
            == []
        )

    def test_a_dispatched_schema_warns_once(self):
        messages = _warnings([_action(schema="dispatch_task('pick')")])

        assert len(messages) == 1
        assert "dispatch_task('pick')" in messages[0]

    def test_record_reads_and_a_dispatched_schema_share_one_warning(self):
        messages = _warnings(
            [_action("Summarise {{ source.page_content }}.", schema="dispatch_task('pick')")]
        )

        assert len(messages) == 1
        assert "source.page_content" in messages[0]
        assert "dispatch_task('pick')" in messages[0]

    def test_a_versioned_action_warns_once_under_its_own_name(self):
        versions = [
            _action(
                "Summarise {{ source.page_content }}.",
                name=f"summarize_{i}",
                is_versioned_agent=True,
                version_base_name="summarize",
            )
            for i in (1, 2, 3)
        ]

        messages = _warnings(versions)

        assert len(messages) == 1
        assert messages[0].startswith("Action 'summarize' has enable_prompt_caching on")

    def test_a_seed_read_by_subscript_is_named(self):
        seed = {"syl": {"select_by": "source.exam", "files": {"a": "$file:a.json"}}}
        action = _action('Rules: {{ seed["syl"].label }}.')
        action["context_scope"] = {"observe": ["source.page_content"], "seed": seed}

        messages = _warnings([action])

        assert len(messages) == 1
        assert 'seed["syl"].label' in messages[0]

    def test_an_inline_macro_gets_no_warning(self):
        assert _warnings([_action("{% macro b(t) %}<{{ t }}>{% endmacro %}{{ b('x') }}")]) == []

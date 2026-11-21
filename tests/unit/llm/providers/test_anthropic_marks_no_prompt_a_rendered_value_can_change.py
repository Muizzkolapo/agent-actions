"""A prompt whose rendered text can change per record gets no cache mark, online."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.validation.static_analyzer.workflow_static_analyzer import analyze_workflow
from tests._support.sdk_http import http_library

# The HTTP library the installed anthropic SDK runs on: httpx, or httpx2 on 1.x.
httpx = http_library(anthropic)

MODEL = "claude-sonnet-4-6"
RECORDS = (
    {"source": {"a": "alpha-page", "exam": "dbt"}},
    {"source": {"a": "beta-page", "exam": "snow"}},
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
    "tpl.json": {"text": "Page: dispatch_task('echo_page')"},
}
ECHO = "def echo_page(context_json):\n    return 'REC:' + str(context_json)\n"
WORKFLOW = {"name": "pages", "run_id": "r1"}


def _marked_texts(value: Any) -> list[str]:
    if isinstance(value, dict):
        own = [value["text"]] if "cache_control" in value else []
        return own + [t for v in value.values() for t in _marked_texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _marked_texts(v)]
    return []


def _transport(sent: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": MODEL,
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    return httpx.MockTransport(handler)


def _config(root: Path, prompt: str, seed: dict[str, Any], **extra: Any) -> dict[str, Any]:
    workflow = root / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    for name, content in SEED_FILES.items():
        (workflow / "seed_data" / name).write_text(json.dumps(content))
    (root / "tools").mkdir()
    (root / "tools" / "echo_page.py").write_text(ECHO)
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
        "context_scope": {"observe": ["source.a"], "seed": seed},
        "workflow_config_path": str(workflow / "agent_config" / "wf.yml"),
        "tool_path": [str(root / "tools")],
        "_project_root": str(root),
        **extra,
    }


def _online(config: dict[str, Any], extra_context: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    for record in RECORDS:
        prepared = PromptPreparationService.prepare_prompt_with_field_context(
            config, "summarize", record["source"], field_context={**record, **extra_context}
        )
        context = MagicMock()
        context.agent_name = "summarize"
        context.agent_config = config
        task = PreparedTask(
            target_id=record["source"]["a"],
            source_guid="sg",
            formatted_prompt=prepared.formatted_prompt,
            llm_context=prepared.llm_context,
        )
        with patch(
            "agent_actions.llm.providers.client_base.get_or_create_client",
            lambda *_a, **_k: anthropic.Anthropic(
                api_key="sk-ant-test", http_client=httpx.Client(transport=_transport(sent))
            ),
        ):
            OnlineStrategy().invoke(task, context)
    return sent


def _prompt_text(body: dict[str, Any]) -> str:
    content = body["messages"][0]["content"]
    text = content if isinstance(content, str) else "".join(b["text"] for b in content)
    return text.split("<|begin_of_text|>")[0]


NO_MARK = {
    "source bound by set": ("{% set x = source %}Summarise {{ x.a }}.", SEED, {}),
    "source bound by for": ("{% for s in [source] %}Summarise {{ s.a }}.{% endfor %}", SEED, {}),
    "source bound by with": ("{% with s = source %}Summarise {{ s.a }}.{% endwith %}", SEED, {}),
    "source as a macro default": (
        "{% macro m(x=source) %}{{ x.a }}{% endmacro %}Summarise {{ m() }}.",
        SEED,
        {},
    ),
    "whole seed with a key chosen per record": ("Rules: {{ seed | tojson }}", SEED, {}),
    "seed value that holds a dispatch call": (
        "{{ seed.tpl.text }}",
        {"tpl": "$file:tpl.json"},
        {},
    ),
    "random filter": (
        "Rules {{ seed.rules.label }}. Example {{ range(1000000) | random }}.",
        SEED,
        {},
    ),
    "lipsum global": ("Rules {{ seed.rules.label }}. {{ lipsum(1) }}", SEED, {}),
}

ONE_SHARED_MARK = {
    "workflow name": ("Workflow {{ workflow.name }}.", SEED, {"workflow": WORKFLOW}, {}),
    "promoted version name": (
        "Version {{ i }} of the summary.",
        SEED,
        {"version": {"i": 1, "length": 2}, "i": 1},
        {"_version_context": {"i": 1, "length": 2}},
    ),
}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-ant-test")


@pytest.mark.parametrize(("prompt", "seed", "extra_context"), NO_MARK.values(), ids=NO_MARK.keys())
def test_a_prompt_whose_text_differs_per_record_carries_no_mark(
    tmp_path, prompt, seed, extra_context
):
    first, second = _online(_config(tmp_path, prompt, seed), extra_context)

    assert _prompt_text(first) != _prompt_text(second)
    assert [_marked_texts(first), _marked_texts(second)] == [[], []]


@pytest.mark.parametrize(
    ("prompt", "seed", "extra_context", "extra_config"),
    ONE_SHARED_MARK.values(),
    ids=ONE_SHARED_MARK.keys(),
)
def test_a_prompt_the_same_for_every_record_keeps_one_shared_mark(
    tmp_path, prompt, seed, extra_context, extra_config
):
    first, second = _online(_config(tmp_path, prompt, seed, **extra_config), extra_context)

    assert _prompt_text(first) == _prompt_text(second)
    assert len(_marked_texts(first)) == 1
    assert _marked_texts(first) == _marked_texts(second)


def test_preflight_names_a_seed_file_that_calls_dispatch(tmp_path):
    action = _config(tmp_path, "{{ seed.tpl.text }}", {"tpl": "$file:tpl.json"})
    action["schema"] = {"summary": "string"}

    result = analyze_workflow({"name": "pages", "actions": [action]})
    messages = [w.message for w in result.warnings if "enable_prompt_caching" in w.message]

    assert len(messages) == 1
    assert "dispatch_task" in messages[0]

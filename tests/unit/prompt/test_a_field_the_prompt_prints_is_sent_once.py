"""An observed field the prompt template prints is not sent again in the context block.

The rendered prompt already holds it, so the request held a long field twice and its input
tokens were paid twice, online and in batch. `context_block: all` keeps the old request.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.batch_base import UNSENT_ERROR_KEY
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.llm.realtime.builder import create_dynamic_agent
from agent_actions.output.response.config_fields import inherit_simple_fields
from agent_actions.processing.task_preparer import write_trace_row
from agent_actions.prompt.context_block import context_block, printed_fields
from agent_actions.prompt.message_builder import MessageBuilder

TEMPLATE = "Summarise this page.\n\n{{ source.page_content }}\n"
PAGE = "Tides rise twice a day along the northern coast. " * 20
URL = "https://example.org/tides-page"
CONTEXT = {"source": {"page_content": PAGE}}
INVOKE = "agent_actions.llm.realtime.services.ClientInvocationService.invoke_client"
ONLINE_VENDORS = ("openai", "anthropic", "gemini", "groq", "cohere")


def _prompt(page: str = PAGE) -> str:
    return TEMPLATE.replace("{{ source.page_content }}", page)


def _config(vendor: str = "anthropic", **settings: Any) -> dict[str, Any]:
    return {
        "agent_type": "assess_scope",
        "model_vendor": vendor,
        "model_name": "claude-sonnet-4-6",
        "prompt": TEMPLATE,
        "json_mode": True,
        "context_scope": {"observe": ["source.page_content"]},
        **settings,
    }


def _sent_online(vendor: str, context: dict[str, Any], prompt: str, **settings: Any) -> str:
    """Every message text the online request carries."""
    with patch(INVOKE, return_value=[{}]) as invoke:
        create_dynamic_agent(_config(vendor, **settings), context, prompt)
    _, _, sent_prompt, sent_context, *_ = invoke.call_args.args
    envelope = MessageBuilder.build(vendor, sent_prompt, sent_context, json_mode=True)
    return "\n".join(message.content for message in envelope.messages)


def _batch_client(vendor: str) -> Any:
    if vendor == "ollama_local":
        return OllamaBatchClient(base_url="http://localhost:11434")
    cls = {
        "openai": OpenAIBatchClient,
        "groq": GroqBatchClient,
        "anthropic": AnthropicBatchClient,
        "gemini": GeminiBatchClient,
    }[vendor]
    client = cls.__new__(cls)
    client.enable_prompt_caching = False
    return client


def _batch_row(context: dict[str, Any], prompt: str) -> dict[str, Any]:
    return {"target_id": "r1", "prompt": prompt, "content": json.loads(json.dumps(context))}


def _sent_in_batch(vendor: str, context: dict[str, Any], prompt: str, **settings: Any) -> str:
    """The batch line, as the provider is sent it."""
    (task,) = _batch_client(vendor).prepare_tasks(
        [_batch_row(context, prompt)], _config(vendor, **settings)
    )
    return json.dumps(task, ensure_ascii=False)


@pytest.mark.parametrize("vendor", ONLINE_VENDORS)
def test_the_online_request_holds_a_printed_page_once(vendor):
    assert _sent_online(vendor, CONTEXT, _prompt()).count(PAGE) == 1


@pytest.mark.parametrize("vendor", ("openai", "groq", "anthropic", "gemini"))
def test_the_batch_line_holds_a_printed_page_once(vendor):
    assert _sent_in_batch(vendor, CONTEXT, _prompt()).count(PAGE) == 1


def _estimate(page: str, **settings: Any) -> int | None:
    """The token guard's estimate for an Anthropic batch line; None when it fits 200,000 tokens."""
    row = _batch_row({"source": {"page_content": page}}, _prompt(page))
    config = _config(context_window=200_000, **settings)
    AnthropicBatchClient.prepare_tasks(_batch_client("anthropic"), [row], config)
    error = row.get(UNSENT_ERROR_KEY)
    return None if error is None else error.context["estimated_tokens"]


def test_the_token_guard_counts_a_printed_page_once():
    page = "x" * 1_000_000

    once, twice = _estimate(page), _estimate(page, context_block="all")

    assert once is not None and twice is not None
    assert once == pytest.approx(len(page) / 4, rel=0.01)
    assert twice == pytest.approx(2 * once, rel=0.01)


def test_a_page_that_fits_once_is_sent():
    page = "x" * 600_000

    assert _estimate(page) is None
    assert _estimate(page, context_block="all") is not None


def test_an_observed_field_the_prompt_does_not_print_stays_in_the_context_block():
    context = {"source": {"page_content": PAGE, "url": URL}}

    online = _sent_online("anthropic", context, _prompt())
    in_batch = _sent_in_batch("anthropic", context, _prompt())

    assert online.count(PAGE) == in_batch.count(PAGE) == 1
    assert online.count(URL) == in_batch.count(URL) == 1


def test_context_block_all_sends_every_observed_field_again():
    assert _sent_online("anthropic", CONTEXT, _prompt(), context_block="all").count(PAGE) == 2
    assert _sent_in_batch("anthropic", CONTEXT, _prompt(), context_block="all").count(PAGE) == 2


def test_context_block_none_sends_no_observed_field():
    context = {"source": {"page_content": PAGE, "url": URL}}

    assert context_block(context, _config(context_block="none"), _prompt()) == {}
    assert URL not in _sent_online("anthropic", context, _prompt(), context_block="none")


def test_a_vendor_that_sends_the_record_in_its_own_message_keeps_it_there():
    assert _sent_in_batch("ollama_local", CONTEXT, _prompt()).count(PAGE) == 2


def test_a_repair_prompt_without_the_page_still_gets_it_in_the_context_block():
    repair_prompt = "Your answer failed a check. Answer again."

    assert context_block(CONTEXT, _config(), repair_prompt) == CONTEXT


def test_a_tool_action_gets_every_field():
    assert context_block(CONTEXT, _config(kind="tool"), _prompt()) == CONTEXT


class _Traces:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def write_prompt_trace(self, **row: Any) -> None:
        self.rows.append(row)


def test_the_trace_shows_the_context_block_that_was_sent():
    class Context:
        agent_name = "assess_scope"
        agent_config = _config()
        storage_backend = _Traces()
        mode = None
        workflow_metadata = None

    context = {"source": {"page_content": PAGE, "url": URL}}
    write_trace_row(
        Context(),
        record_id="r1",
        source_guid="g1",
        prompt=_prompt(),
        llm_context=context,
        attempt=0,
    )

    (row,) = Context.storage_backend.rows
    assert json.loads(row["llm_context"]) == {"source": {"url": URL}}


@pytest.mark.parametrize(
    ("template", "printed"),
    [
        ("{{ source.page_content }}", (("source", "page_content"),)),
        ("{{ source['page_content'] }}", (("source", "page_content"),)),
        ("{{ extract.meta.title }}", (("extract", "meta", "title"),)),
        ("{% if x %}{{ source.page_content }}{% endif %}", ()),
        ("{% for p in pages %}{{ source.page_content }}{% endfor %}", ()),
        ("{{ source.page_content | truncate(10) }}", ()),
        ("{{ source }}", ()),
        ("{% set page = source %}{{ page.page_content }}", (("source", "page_content"),)),
        ("{% set source = {'page_content': 'x'} %}{{ source.page_content }}", ()),
    ],
)
def test_only_a_field_printed_as_it_is_at_the_top_level_counts(template, printed):
    assert printed_fields(template) == printed


@pytest.mark.parametrize("value", ["auto", "all", "none"])
def test_context_block_is_a_setting_of_an_action_and_of_the_defaults(value):
    assert DefaultsConfig(context_block=value).context_block == value
    action = ActionConfig(name="a", intent="i", context_block=value)
    assert action.context_block == value


def test_an_unknown_context_block_is_refused():
    with pytest.raises(ValidationError, match="context_block"):
        DefaultsConfig(context_block="some")


def test_an_action_inherits_context_block_and_defaults_to_auto():
    agent: dict[str, Any] = {}
    inherit_simple_fields(agent, {}, {"context_block": "all"})
    assert agent["context_block"] == "all"

    inherit_simple_fields(agent, {}, {})
    assert agent["context_block"] == "auto"

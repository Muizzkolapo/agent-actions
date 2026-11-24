"""A `{% cache_point %}` changes no text the model reads, and record text cannot fake one.

The mark that stood where a tag rendered was two fixed private-use characters, and every
rendered prompt was searched for them, with or without a tag: a record holding them lost
them, and five pairs in a record raised. A tag at the end of a line of text joined the line
to the next one. A prompt that held the word `cache_point` was rendered though it had no
tag, and adding or removing a tag was taken as an edit of the action.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.processing.invocation.batch import BatchStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.prompt.cache_scope import cache_point_use
from agent_actions.prompt.message_builder import PROVIDER_MESSAGE_CONFIGS, MessageBuilder
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.workflow.executor import _compute_action_config_hash

OLD_MARK = chr(0xE006) + chr(0xE007)


def _prepare(prompt: str, fact: str = "one", **extra: Any) -> Any:
    config = {
        "agent_type": "write",
        "name": "write",
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content", "slots.fact"]},
        **extra,
    }
    return PromptPreparationService.prepare_prompt_with_field_context(
        agent_config=config,
        agent_name="write",
        contents={},
        field_context={"source": {"page_content": "The page."}, "slots": {"fact": fact}},
    )


class TestRecordText:
    def test_the_old_mark_in_a_record_is_sent_as_written(self):
        fact = f"Page {OLD_MARK} icon"

        prepared = _prepare("Facts: {{ slots.fact }}", fact)

        assert prepared.formatted_prompt == f"Facts: {fact}"
        assert prepared.cache_points == ()

    def test_five_pairs_in_a_record_raise_nothing(self):
        fact = OLD_MARK * 5

        prepared = _prepare("{{ source.page_content }}{% cache_point %}{{ slots.fact }}", fact)

        assert prepared.formatted_prompt == f"The page.{fact}"
        assert prepared.cache_points == (len("The page."),)

    def test_with_a_tag_the_point_is_still_found(self):
        prepared = _prepare("{{ source.page_content }}\n{% cache_point %}\n{{ slots.fact }}")

        assert prepared.formatted_prompt == "The page.\none"
        assert prepared.cache_points == (len("The page.\n"),)


@pytest.mark.parametrize(
    ("template", "without"),
    [
        ("Page {{ slots.fact }} {% cache_point %}\nSlot", "Page {{ slots.fact }} \nSlot"),
        ("Page {{ slots.fact }}\n{% cache_point %}\nSlot", "Page {{ slots.fact }}\nSlot"),
        ("Page {{ slots.fact }} {%- cache_point -%}\nSlot", "Page {{ slots.fact }}Slot"),
        (
            "Page {{ slots.fact }}{% cache_point %} after\nSlot",
            "Page {{ slots.fact }} after\nSlot",
        ),
    ],
    ids=["tag-at-the-end-of-a-line", "tag-alone-on-its-line", "tag-that-trims", "tag-mid-line"],
)
def test_the_text_is_the_text_without_the_tag(template, without):
    assert _prepare(template).formatted_prompt == _prepare(without).formatted_prompt


def test_a_tag_at_the_end_of_a_macro_line_keeps_the_line_apart(tmp_path: Path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "house.jinja2").write_text(
        "{% macro rules() %}House rules: answer in one line. {% cache_point %}{% endmacro %}"
    )
    workflow = tmp_path / "wf.yml"
    workflow.write_text(
        '{% from "house.jinja2" import rules %}\n'
        "actions:\n"
        "  - name: write\n"
        "    intent: Write\n"
        "    prompt: |\n"
        "      {{ rules() }}\n"
        "      Q {{ '{{' }} slots.fact {{ '}}' }}\n"
    )
    rendered = render_pipeline_with_templates(
        workflow, templates, compile_schemas=False, project_root=tmp_path
    )
    (action,) = yaml.safe_load(rendered)["actions"]

    prepared = _prepare(action["prompt"], "r1")

    assert prepared.formatted_prompt.startswith("House rules: answer in one line. \nQ r1")


def test_the_word_cache_point_in_a_prompt_is_no_tag():
    prompt = "Explain the cache_point idea. Keep {{ name }} as written."

    assert PromptPreparationService._render_prompt_template(prompt, {}) == prompt


@pytest.mark.parametrize(
    "marked",
    [
        "{{ source.page_content }}\n{% cache_point %}{{ slots.fact }}",
        "{{ source.page_content }}\n{% cache_point %}\n{{ slots.fact }}",
        "{{ source.page_content }}\n  {%- cache_point %}  \n{{ slots.fact }}",
        "{{ source.page_content }}\n{{ slots.fact }}\n{% cache_point %}",
    ],
    ids=["before-text", "own-line", "own-line-trimming", "last-line"],
)
def test_adding_or_removing_a_tag_is_no_edit_of_the_action(marked):
    plain = {"prompt": "{{ source.page_content }}\n{{ slots.fact }}"}
    if marked.endswith("%}"):
        plain = {"prompt": plain["prompt"] + "\n"}
    edited = {"prompt": "{{ source.page_content }}\n{{ slots.other }}"}

    assert _compute_action_config_hash({"prompt": marked}) == _compute_action_config_hash(plain)  # type: ignore[arg-type]
    assert _compute_action_config_hash(edited) != _compute_action_config_hash(plain)  # type: ignore[arg-type]


def test_a_tag_in_a_raw_block_stays_as_written():
    prompt = "{% raw %}\nPage {% cache_point %}\nnext\n{% endraw %}"

    prepared = _prepare(prompt)

    assert prepared.formatted_prompt == "\nPage {% cache_point %}\nnext\n"
    assert prepared.cache_points == ()


def _use(prompt: str) -> Any:
    return cache_point_use(
        {"name": "write", "prompt": prompt, "context_scope": {"observe": ["source.page"]}}
    )


def test_a_dispatch_call_after_the_last_tag_does_not_change_the_marked_text():
    assert _use("Rules.{% cache_point %} dispatch_task('pick_rule')").changing == ()


def test_a_dispatch_call_before_the_tag_changes_the_marked_text():
    use = _use("dispatch_task('pick_rule') Rules.{% cache_point %}")

    assert use.changing == ("dispatch_task('pick_rule')",)


@pytest.mark.parametrize("vendor", sorted(PROVIDER_MESSAGE_CONFIGS))
def test_every_vendor_sends_the_old_mark_in_a_record_as_written(vendor):
    fact = f"Page {OLD_MARK} icon"
    prepared = _prepare("Facts: {{ slots.fact }}", fact)

    envelope = MessageBuilder.build(
        vendor,
        prepared.formatted_prompt,
        prepared.llm_context,
        json_mode=False,
        enable_prompt_caching=True,
        cache_points=prepared.cache_points,
    )

    assert f"Facts: {fact}" in json.dumps(envelope.to_dicts(), ensure_ascii=False)


def _anthropic_config(prompt: str) -> dict[str, Any]:
    return {
        "agent_type": "write",
        "action_name": "write",
        "name": "write",
        "model_vendor": "anthropic",
        "model_name": "claude-sonnet-4-6",
        "json_mode": False,
        "granularity": "record",
        "enable_prompt_caching": True,
        "prompt": prompt,
        "context_scope": {"observe": ["source.fact"]},
    }


def test_an_anthropic_batch_with_caching_on_sends_five_pairs_in_a_record(tmp_path: Path):
    fact = OLD_MARK * 5
    client = AnthropicBatchClient(api_key="sk-ant-test", enable_prompt_caching=True)
    data = [{"target_id": "r1", "source_guid": "sg-r1", "content": {"fact": fact}}]

    prepared = BatchTaskPreparator(
        action_indices={}, dependency_configs={}, storage_backend=MagicMock()
    ).prepare_tasks(
        agent_config=_anthropic_config("Facts: {{ source.fact }}"),
        data=data,
        provider=client,
        output_directory=str(tmp_path),
    )
    (task,) = prepared.tasks

    assert f"Facts: {fact}" in json.dumps(task, ensure_ascii=False)


def test_a_batch_strategy_sends_the_cache_points_of_each_task_to_anthropic():
    client = AnthropicBatchClient(api_key="sk-ant-test", enable_prompt_caching=True)
    context = MagicMock()
    context.agent_config = _anthropic_config("Rules.{% cache_point %} {{ source.fact }}")
    strategy = BatchStrategy(client)
    for target_id in ("r1", "r2"):
        strategy.invoke(
            PreparedTask(
                target_id=target_id,
                source_guid="sg-1",
                formatted_prompt=f"Rules. {target_id}",
                llm_context={"fact": target_id},
                cache_points=(len("Rules."),),
            ),
            context,
        )

    with patch.object(client, "submit_batch", return_value=("b1", "submitted")) as submit:
        strategy.flush("pages")

    (lines, _name, _directory), _ = submit.call_args
    for line in lines:
        (message,) = line["params"]["messages"]
        first, *_rest = message["content"]
        assert first["text"].endswith("Rules.")
        assert first["cache_control"] == {"type": "ephemeral"}

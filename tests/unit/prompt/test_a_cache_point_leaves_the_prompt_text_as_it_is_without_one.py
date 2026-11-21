"""A `{% cache_point %}` in a prompt template leaves the rendered text as it is without the tag, and says where it stood."""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.prompt.service import PromptPreparationService

PAGE = "The page.\nIts second line."
WITH_POINT = """\
## PAGE
{{ source.page_content }}
{% cache_point %}
## THE SLOT
{{ slots.fact }}
"""
WITHOUT_POINT = """\
## PAGE
{{ source.page_content }}
## THE SLOT
{{ slots.fact }}
"""


def _prepare(prompt: str, fact: str = "one") -> Any:
    config = {
        "agent_type": "write",
        "name": "write",
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content", "slots.fact"]},
    }
    return PromptPreparationService.prepare_prompt_with_field_context(
        agent_config=config,
        agent_name="write",
        contents={},
        field_context={"source": {"page_content": PAGE}, "slots": {"fact": fact}},
    )


class TestTheRenderedText:
    def test_a_cache_point_on_its_own_line_takes_the_line_with_it(self):
        assert _prepare(WITH_POINT).formatted_prompt == _prepare(WITHOUT_POINT).formatted_prompt

    def test_a_cache_point_inside_a_line_leaves_the_text_around_it(self):
        marked = _prepare("Page: {{ source.page_content }}{% cache_point %} Slot: {{ slots.fact }}")
        plain = _prepare("Page: {{ source.page_content }} Slot: {{ slots.fact }}")

        assert marked.formatted_prompt == plain.formatted_prompt

    def test_an_indented_cache_point_line_leaves_no_blank_line_or_spaces(self):
        marked = _prepare("a {{ slots.fact }}\n    {% cache_point %}\nb\n")

        assert marked.formatted_prompt == "a one\nb\n"

    def test_whitespace_control_strips_as_on_any_block_tag(self):
        marked = _prepare("a {{ slots.fact }}\n\n{%- cache_point %}\nb\n")

        assert marked.formatted_prompt == "a oneb\n"

    def test_the_rendered_text_holds_no_trace_of_the_tag(self):
        text = _prepare(WITH_POINT).formatted_prompt

        assert "cache_point" not in text
        assert all(ord(char) < 0xE000 or ord(char) > 0xF8FF for char in text)

    def test_a_filter_over_the_tag_leaves_no_trace_of_it_either(self):
        marked = _prepare("{% filter upper %}a{% cache_point %}b{% endfilter %} {{ slots.fact }}")

        assert marked.formatted_prompt == "AB one"
        assert marked.cache_points == (1,)

    def test_a_tag_in_inline_code_stays_text(self):
        marked = _prepare("Write `{% cache_point %}` after {{ slots.fact }}.")

        assert marked.formatted_prompt == "Write `{% cache_point %}` after one."
        assert marked.cache_points == ()


class TestWhereThePointStood:
    def test_the_point_is_the_length_of_the_text_before_the_tag(self):
        prepared = _prepare(WITH_POINT)

        assert prepared.cache_points == (len(f"## PAGE\n{PAGE}\n"),)
        (point,) = prepared.cache_points
        assert prepared.formatted_prompt[point:] == "## THE SLOT\none\n"

    def test_two_records_of_one_page_share_the_text_before_the_point(self):
        first, second = _prepare(WITH_POINT, "one"), _prepare(WITH_POINT, "two")

        assert first.cache_points == second.cache_points
        (point,) = first.cache_points
        assert first.formatted_prompt[:point] == second.formatted_prompt[:point]
        assert first.formatted_prompt[point:] != second.formatted_prompt[point:]

    def test_several_points_are_given_in_order(self):
        prepared = _prepare("a{% cache_point %}b {{ slots.fact }}{% cache_point %}c")

        assert prepared.formatted_prompt == "ab onec"
        assert prepared.cache_points == (1, 6)

    def test_a_point_in_a_branch_not_taken_is_not_given(self):
        prepared = _prepare("a{% if slots.fact == 'none' %}{% cache_point %}{% endif %}b")

        assert prepared.formatted_prompt == "ab"
        assert prepared.cache_points == ()

    def test_a_template_without_a_tag_has_no_points(self):
        assert _prepare(WITHOUT_POINT).cache_points == ()


@pytest.mark.parametrize("prompt", ["Static text.\n{% cache_point %}\nMore.", "{% cache_point %}"])
def test_a_prompt_rendered_with_no_context_drops_the_tag_too(prompt):
    rendered = PromptPreparationService._render_prompt_template(prompt, {})

    assert "cache_point" not in rendered
    assert "{%" not in rendered

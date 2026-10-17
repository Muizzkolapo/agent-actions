"""PromptLoader.load_prompt_expanded puts each loaded prompt in as written."""

from pathlib import Path

import pytest

from agent_actions.prompt.handler import PromptLoader


def _store(tmp_path: Path, **prompts: str) -> Path:
    (tmp_path / "prompt_store").mkdir()
    body = "".join(
        f"{{prompt {name}}}\n{text}\n{{end_prompt}}\n\n" for name, text in prompts.items()
    )
    (tmp_path / "prompt_store" / "p.md").write_text(body)
    return tmp_path


def test_the_loaded_text_keeps_its_own_tags_for_the_record(tmp_path):
    root = _store(tmp_path, H="Title: {{ source.title }}", M='{{ load_prompt("p.H") }}\nBody')

    assert PromptLoader.load_prompt_expanded("p.M", root) == "Title: {{ source.title }}\nBody"


def test_whitespace_control_strips_around_the_tag_as_jinja_does(tmp_path):
    root = _store(tmp_path, H="head", M="A\n  {{- load_prompt('p.H') -}}  \nB")

    assert PromptLoader.load_prompt_expanded("p.M", root) == "AheadB"


def test_a_call_in_a_raw_block_is_left_as_written(tmp_path):
    raw = '{% raw %}{{ load_prompt("p.H") }}{% endraw %}'
    root = _store(tmp_path, H="head", M=raw)

    assert PromptLoader.load_prompt_expanded("p.M", root) == raw


def test_a_prompt_that_loads_itself_fails_naming_the_cycle(tmp_path):
    root = _store(tmp_path, M='{{ load_prompt("p.M") }}')

    with pytest.raises(ValueError, match=r"cycle: p\.M -> p\.M"):
        PromptLoader.load_prompt_expanded("p.M", root)


@pytest.mark.parametrize(
    "call",
    [
        '{{ load_prompt("p.H") | upper }}',
        "{{ load_prompt(name) }}",
        '{% set h = load_prompt("p.H") %}{{ h }}',
    ],
)
def test_a_call_the_load_cannot_expand_is_refused(tmp_path, call):
    root = _store(tmp_path, H="head", M=call)

    with pytest.raises(ValueError, match="calls load_prompt in a form the load cannot expand"):
        PromptLoader.load_prompt_expanded("p.M", root)


def test_a_prompt_without_calls_is_loaded_unchanged(tmp_path):
    text = "{% if source.x %}{{ source.x }}{% endif %}"
    root = _store(tmp_path, M=text)

    assert PromptLoader.load_prompt_expanded("p.M", root) == PromptLoader.load_prompt("p.M", root)

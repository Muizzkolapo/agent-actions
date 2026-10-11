"""An explicit `-%}` on the file's last tag still strips the line break after it.

Restoring the newline Jinja drops from the end of the workflow file must not undo what
the author asked for: `{% endif -%}` strips the whitespace after it, and at the end of
the file that whitespace is the final newline.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates

HEAD = """\
name: wf
description: d
version: "1.0"
defaults: {model_vendor: openai, model_name: gpt-4, api_key: K}
actions:
  - name: summarize
    intent: i
    prompt: |
      {% if true %}Hello extra{% endif CLOSE%}
"""


def _prompt(tmp_path: Path, close: str) -> str:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    path = tmp_path / "wf.yml"
    path.write_text(HEAD.replace("CLOSE", close))
    rendered = render_pipeline_with_templates(path, folder, compile_schemas=False)
    return yaml.safe_load(rendered)["actions"][0]["prompt"]


def test_a_closing_tag_that_strips_after_it_leaves_no_final_newline(tmp_path):
    assert _prompt(tmp_path, "-") == "Hello extra"


def test_the_same_tag_without_the_strip_keeps_its_newline(tmp_path):
    """Control: the line break is restored where nothing asked for it to go."""
    assert _prompt(tmp_path, "") == "Hello extra\n"


@pytest.mark.parametrize("tag", ["-}}", "-%}", "-#}"])
def test_every_right_strip_spelling_is_respected(tmp_path, tag):
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    path = tmp_path / "wf.yml"
    spelled = {
        "-}}": "{{ 'Hello extra' -}}",
        "-%}": "Hello extra{% set tone = 1 -%}",
        "-#}": "Hello extra{#- end -#}",
    }
    path.write_text(HEAD.replace("{% if true %}Hello extra{% endif CLOSE%}", spelled[tag]))

    prompt = yaml.safe_load(render_pipeline_with_templates(path, folder, compile_schemas=False))[
        "actions"
    ][0]["prompt"]

    assert not prompt.endswith("\n")


def _render(tmp_path: Path, text: str) -> dict:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    path = tmp_path / "wf.yml"
    path.write_text(text)
    return yaml.safe_load(render_pipeline_with_templates(path, folder, compile_schemas=False))


class TestWhatDoesNotStripIsNotTreatedAsStripping:
    def test_a_strip_that_takes_several_trailing_newlines_takes_them_all(self, tmp_path):
        """One restored newline would put back a line break the tag removed."""
        text = HEAD.replace("CLOSE", "-") + "\n\n"

        assert _render(tmp_path, text)["actions"][0]["prompt"] == "Hello extra"

    def test_a_strip_tag_earlier_in_the_file_does_not_reach_the_end(self, tmp_path):
        """The check is on the last tag: an earlier `-%}` is no reason to drop the
        prompt's own final newline."""
        text = "{% set unused = 1 -%}\n" + HEAD.replace("CLOSE", "")

        assert _render(tmp_path, text)["actions"][0]["prompt"] == "Hello extra\n"

    def test_a_keep_marker_is_not_a_strip(self, tmp_path):
        """`+%}` asks for the whitespace to stay, so the newline is restored."""
        assert _prompt(tmp_path, "+") == "Hello extra\n"

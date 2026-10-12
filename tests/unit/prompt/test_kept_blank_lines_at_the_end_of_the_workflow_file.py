"""A block value with kept blank lines is the same at the end of the file as in the middle.

Jinja drops one final newline from the source it renders. A value that keeps its
trailing blank lines (`|+`) ends the file with more than one, so what is left after the
drop still ends with a newline, and restoring the dropped one only when the output does
not end with one would lose a line break at the end of the file that it has elsewhere.
"""

from pathlib import Path

import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates

HEAD = """\
name: wf
description: d
version: "1.0"
defaults: {model_vendor: openai, model_name: gpt-4, api_key: K}
actions:
  - name: summarize
    prompt: Summarize the page.
    intent: |+
      Summarise.

"""

EXPECT = "    expect: { repair: none }\n"


def _intent(tmp_path: Path, workflow: str) -> str:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(path, folder, compile_schemas=False)
    return yaml.safe_load(rendered)["actions"][0]["intent"]


def test_the_kept_blank_line_survives_at_the_end_of_the_file(tmp_path):
    assert _intent(tmp_path, HEAD) == "Summarise.\n\n"


def test_the_value_is_the_same_with_a_key_after_it(tmp_path):
    (tmp_path / "other").mkdir()

    last = _intent(tmp_path, HEAD)
    middle = _intent(tmp_path / "other", HEAD + EXPECT)

    assert last == middle == "Summarise.\n\n"

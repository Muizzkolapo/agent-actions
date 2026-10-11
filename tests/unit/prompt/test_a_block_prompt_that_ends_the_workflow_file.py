"""A block prompt that ends the workflow file keeps its final newline.

The workflow file is rendered through Jinja before it is parsed, and Jinja drops the
final newline of any source it renders. For a block scalar that is the value's own line
break, so the last action's prompt was sent without it, while the same prompt anywhere
else in the file kept it. The prompt is part of the action's config hash, so adding an
action below it, which gives the newline back, read as an edit and reset an action
nobody had touched.
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
    intent: i
    prompt: |
      Summarize the page.
"""

SECOND = """\
  - name: tag
    dependencies: [summarize]
    intent: i
    prompt: |
      Tag the page.
"""


def _render(tmp_path: Path, workflow: str, templates: dict[str, str] | None = None) -> dict:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    for name, text in (templates or {}).items():
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(path, folder, compile_schemas=False)
    return yaml.safe_load(rendered)


def _prompts(config: dict) -> dict[str, str]:
    return {action["name"]: action["prompt"] for action in config["actions"]}


class TestTheLastPromptOfTheFileKeepsItsNewline:
    def test_a_block_prompt_that_ends_the_file_ends_with_its_newline(self, tmp_path):
        assert _prompts(_render(tmp_path, HEAD))["summarize"] == "Summarize the page.\n"

    def test_the_last_prompt_is_what_it_was_before_an_action_was_added_below_it(self, tmp_path):
        """Config hashing reads the prompt text, so a prompt that changes when a
        neighbour is added resets an action nobody edited."""
        alone = _prompts(_render(tmp_path, HEAD))["summarize"]
        (tmp_path / "other").mkdir()
        beside = _prompts(_render(tmp_path / "other", HEAD + SECOND))["summarize"]

        assert alone == beside

    def test_the_new_last_action_also_keeps_its_newline(self, tmp_path):
        assert _prompts(_render(tmp_path, HEAD + SECOND))["tag"] == "Tag the page.\n"


class TestWhatItMustNotChange:
    def test_a_prompt_in_the_middle_of_the_file_is_unchanged(self, tmp_path):
        prompts = _prompts(_render(tmp_path, HEAD + SECOND))

        assert prompts["summarize"] == "Summarize the page.\n"

    def test_a_file_that_does_not_end_in_a_newline_gains_none(self, tmp_path):
        """The newline is restored, not invented."""
        prompts = _prompts(_render(tmp_path, HEAD.rstrip("\n")))

        assert prompts["summarize"] == "Summarize the page."

    def test_an_included_templates_file_is_joined_to_what_follows_it_as_before(self, tmp_path):
        """The setting belongs to the workflow file, not to every template it pulls in:
        an include's text was joined to what follows it, and a prompt written so must
        not change under the actions that use it."""
        workflow = HEAD.replace(
            "    prompt: |\n      Summarize the page.\n",
            "    prompt: \"{% include 'tone.j2' %} Summarize the page.\"\n",
        )

        prompts = _prompts(_render(tmp_path, workflow, {"tone.j2": "Write formally.\n"}))

        assert prompts["summarize"] == "Write formally. Summarize the page."

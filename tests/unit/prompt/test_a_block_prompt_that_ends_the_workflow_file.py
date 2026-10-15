"""A block prompt that ends the workflow file keeps its final newline.

The workflow file is rendered through Jinja before it is parsed, and Jinja drops the
final newline of any source it renders. For a block scalar that is the value's own line
break, so the last action's prompt was sent without it, while the same prompt anywhere
else in the file kept it. The prompt is part of the action's config hash, so adding an
action below it, which gives the newline back, read as an edit and reset an action
nobody had touched.
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


def _last_action(prompt: str, keep: str = "|") -> str:
    """An action after `summarize` whose prompt is a block scalar, as the last key."""
    body = "".join(f"      {line}\n" for line in prompt.split("\n"))
    return (
        "  - name: tag\n"
        "    dependencies: [summarize]\n"
        "    intent: i\n"
        "    context_scope: { observe: [summarize.summary, source.page_content] }\n"
        f"    prompt: {keep}\n{body}"
    )


def _middle_action(prompt: str, keep: str = "|") -> str:
    """The same action, with a key after the prompt."""
    return _last_action(prompt, keep) + "    expect: { repair: none }\n"


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


PER_RECORD_PROMPTS = {
    "a field of the record": "Summarize {{ source.page_content }}.",
    "an upstream action": "Use {{ summarize.summary }} please.",
    "text and a field": "Be formal. Summarize {{ source.page_content }}.",
}


class TestAPromptLeftForTheRecordKeepsItsNewlineToo:
    """A prompt that reads what only a record supplies is rendered for each record, from
    the text the load left. It is the usual prompt, and the same position bug applied."""

    @pytest.mark.parametrize("prompt", PER_RECORD_PROMPTS.values(), ids=PER_RECORD_PROMPTS)
    def test_it_ends_with_its_newline_as_the_last_action(self, tmp_path, prompt):
        rendered = _prompts(_render(tmp_path, HEAD + _last_action(prompt)))

        assert rendered["tag"] == prompt + "\n"

    @pytest.mark.parametrize("prompt", PER_RECORD_PROMPTS.values(), ids=PER_RECORD_PROMPTS)
    def test_it_is_what_it_is_with_a_key_after_it(self, tmp_path, prompt):
        """Config hashing reads this text, so a position that changes it resets an
        action nobody edited."""
        last = _prompts(_render(tmp_path, HEAD + _last_action(prompt)))["tag"]
        (tmp_path / "other").mkdir()
        middle = _prompts(_render(tmp_path / "other", HEAD + _middle_action(prompt)))["tag"]

        assert last == middle

    def test_kept_blank_lines_are_restored_exactly_once(self, tmp_path):
        """`|+` keeps every trailing newline; none may be added or lost for the position."""
        prompt = "Summarize {{ source.page_content }}.\n"
        last = _prompts(_render(tmp_path, HEAD + _last_action(prompt, "|+")))["tag"]
        (tmp_path / "other").mkdir()
        middle = _prompts(_render(tmp_path / "other", HEAD + _middle_action(prompt, "|+")))["tag"]

        assert last == middle


class TestABlockValueThatIsNotAPromptKeepsItsNewlineToo:
    def test_a_block_intent_that_ends_the_file_keeps_its_newline(self, tmp_path):
        workflow = HEAD.replace(
            "    intent: i\n    prompt: |\n      Summarize the page.\n",
            "    prompt: Summarize the page.\n    intent: |\n      Summarise.\n",
        )

        config = _render(tmp_path, workflow)

        assert config["actions"][0]["intent"] == "Summarise.\n"


class TestAnIncludeIsStillJoinedToWhatFollowsIt:
    def test_a_block_prompt_that_includes_a_templates_file_is_joined_as_before(self, tmp_path):
        """The shape where the setting belongs to the environment would show: the
        include's own final newline would come between it and the text after it."""
        workflow = HEAD.replace(
            "    prompt: |\n      Summarize the page.\n",
            "    prompt: |\n      {% include 'tone.j2' %}Summarize the page.\n",
        )

        prompts = _prompts(_render(tmp_path, workflow, {"tone.j2": "Write formally.\n"}))

        assert prompts["summarize"] == "Write formally.Summarize the page.\n"

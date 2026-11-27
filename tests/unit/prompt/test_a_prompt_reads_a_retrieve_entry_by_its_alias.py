"""`retrieve.<entry>` in a prompt or guard is the action's retrieve step to every later check."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.validation.static_analyzer import analyze_workflow
from tests.helpers.knowledge import FakeBase, install_fake_knowledge

WF = "agent_workflow/wf/agent_config/wf.yml"
PROMPT = (
    "Answer {{ source.text }} from:\n"
    "{% for m in retrieve.help.matches %}{{ m.text }}{% endfor %}"
    "{% if retrieve.help.count == 0 %}nothing; 'retrieve.help' stays text{% endif %}"
)


@pytest.fixture(autouse=True)
def knowledge(monkeypatch):
    return install_fake_knowledge(monkeypatch, FakeBase("help_center"))


def _render(tmp_path: Path, prompt: str = PROMPT, guard=None) -> dict:
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
    reply = {
        "name": "write_reply",
        "intent": "reply",
        "prompt": prompt,
        "schema": {"reply": "string"},
        "context_scope": {
            "observe": ["source.text"],
            "retrieve": {"help": {"from": "help_center", "query": "source.text"}},
        },
    }
    if guard is not None:
        reply["guard"] = guard
    workflow = tmp_path / WF
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        yaml.safe_dump(
            {
                "name": "wf",
                "description": "d",
                "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
                "actions": [reply],
            },
            sort_keys=False,
        )
    )
    return yaml.safe_load(
        render_pipeline_with_templates(
            workflow, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
        )
    )


def _by_name(rendered: dict) -> dict:
    return {a["name"]: a for a in rendered["actions"]}


def test_the_prompt_reads_the_step_by_its_name_and_quoted_text_is_kept(tmp_path):
    reply = _by_name(_render(tmp_path))["write_reply"]
    prompt = " ".join(reply["prompt"].split())

    assert "{% for m in write_reply__help.matches %}" in prompt
    assert "{% if write_reply__help.count == 0 %}" in prompt
    assert "'retrieve.help' stays text" in prompt
    assert "_retrieve_steps" not in reply


def test_a_prompt_alias_of_no_entry_is_refused(tmp_path):
    with pytest.raises(ConfigurationError, match="retrieve.other.*entries: help"):
        _render(tmp_path, prompt="{{ retrieve.other.matches }}")


def test_the_analyzer_and_dependency_inference_see_the_step_as_an_action(tmp_path):
    rendered = _render(tmp_path, guard={"condition": "retrieve.help.count > 0"})
    actions = _by_name(rendered)

    result = analyze_workflow(rendered)

    assert result.is_valid, [str(e) for e in result.errors]
    inferred = infer_dependencies(actions["write_reply"], list(actions), "write_reply")
    assert "write_reply__help" in [*inferred[0], *inferred[1]]


def test_an_unknown_field_of_the_step_is_caught_by_the_analyzer(tmp_path):
    rendered = _render(tmp_path, prompt="{{ retrieve.help.answers }}")

    result = analyze_workflow(rendered)

    assert any("answers" in str(error) for error in result.errors)

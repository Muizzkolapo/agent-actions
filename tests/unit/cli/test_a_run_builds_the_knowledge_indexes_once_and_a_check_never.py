"""The starter template with retrieve entries: inspect builds nothing, a run builds once."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.helpers.knowledge import FakeBase, install_fake_knowledge

TEMPLATE = Path(__file__).parents[3] / "agent_actions/cli/project_templates/sandbox"
WORKFLOW = "agent_workflow/support_desk/agent_config/support_desk.yml"


@pytest.fixture
def knowledge(monkeypatch):
    return install_fake_knowledge(
        monkeypatch,
        FakeBase("help_center", index=["keyword", "fuzzy"], metadata_fields={"product"}),
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    shutil.copytree(TEMPLATE, root)
    config = root / "agent_actions.yml"
    config.write_text(config.read_text().replace("__PROJECT_NAME__", "demo"))
    workflow = root / WORKFLOW
    data = yaml.safe_load(workflow.read_text())
    actions = {a.get("name"): a for a in data["actions"]}
    # Beside the template's own entry `similar`, which searches the records of read_ticket.
    actions["classify"]["context_scope"]["retrieve"]["help"] = {
        "from": "help_center",
        "query": ["read_ticket.text"],
        "where": {"product": "read_ticket.queue"},
        "top_k": 3,
    }
    actions["billing_team"]["context_scope"]["retrieve"] = {
        "policy": {"from": "help_center", "method": ["keyword", "fuzzy"], "query": "source.text"}
    }
    workflow.write_text(yaml.safe_dump(data, sort_keys=False))
    prompts = root / "prompt_store/support_desk.md"
    prompts.write_text(
        prompts.read_text().replace(
            "\nSimilar tickets:",
            "{% for m in retrieve.help.matches %}{{ m.text }}{% endfor %}\nSimilar tickets:",
            1,
        )
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return root


def _agac(*args: str):
    return CliRunner().invoke(cli, list(args), catch_exceptions=False)


def test_inspect_validates_the_steps_and_builds_no_index(project, knowledge):
    result = _agac("inspect", "-w", "support_desk")

    output = " ".join(result.output.split())
    assert result.exit_code == 0, result.output
    assert "classify: retrieve 'help' from knowledge base help_center by keyword on" in output
    assert "billing_team__policy" in output
    # The starter's own entry, on draft_reply in the loop: its steps are shown, by name.
    assert (
        "reply_round_iter1__draft_reply__help reply_round_iter1__draft_reply: retrieve 'help' "
        "from knowledge base help_center by keyword on source.text, top 2"
    ) in output
    assert knowledge.ensured == []
    assert knowledge.hashed == []
    assert knowledge.searched == []


@pytest.mark.parametrize(
    "command",
    [["schema"], ["retry", "--dry-run", "--sandbox"], ["dispositions", "--sandbox"]],
    ids=["schema", "retry-dry-run", "dispositions"],
)
def test_a_command_that_loads_the_workflow_without_running_it_builds_no_index(
    project, knowledge, command
):
    assert _agac("run", "-w", "support_desk", "--sandbox", "--wait").exit_code == 0
    built = len(knowledge.ensured)

    result = _agac(*command, "-w", "support_desk")

    assert result.exit_code == 0, result.output
    assert len(knowledge.ensured) == built


def test_a_run_builds_each_index_once_and_searches_with_its_digest(project, knowledge):
    result = _agac("run", "-w", "support_desk", "--sandbox", "--wait")

    assert result.exit_code == 0, result.output
    assert sorted(sorted(kinds) for _, _, kinds, _ in knowledge.ensured) == [
        ["fuzzy", "keyword"],
        ["keyword"],
    ]
    assert all(sandbox for *_, sandbox in knowledge.ensured)
    assert knowledge.searched
    assert {call["digest"] for call in knowledge.searched} == {knowledge.digest}


def test_a_rerun_of_the_action_answers_its_retrieve_step_again(project, knowledge):
    assert _agac("run", "-w", "support_desk", "--sandbox", "--wait").exit_code == 0
    searched = len(knowledge.searched)

    result = _agac("run", "-w", "support_desk", "--sandbox", "--wait", "--rerun", "classify")

    assert result.exit_code == 0, result.output
    assert len(knowledge.searched) > searched
    assert len(knowledge.ensured) == 4


def test_a_scenario_cannot_stub_a_retrieve_step(project, knowledge):
    (project / "sandbox.yml").write_text("actions:\n  classify__help: {stub: true}\n")

    result = _agac("inspect", "-w", "support_desk", "--sandbox")

    assert result.exit_code != 0, result.output
    assert "is a retrieve step" in " ".join(result.output.split())
    assert knowledge.ensured == []

"""The starter template grounds its reply in help articles: draft_reply retrieves for each ticket.

The retrieve entry ``help`` of ``draft_reply`` (in the ``reply_round`` loop) searches the
``help_center`` knowledge base with ``source.text``, so the search reads real ticket text in a
sandbox run. Its step in the first round is ``reply_round_iter1__draft_reply__help``. It takes
draft_reply's dependencies, so it searches only for the records that reach draft_reply.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "support_desk"
STEP = "reply_round_iter1__draft_reply__help"
ENV = {"OPENAI_API_KEY": ""}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    created = run_agac(tmp_path, "init", "demo", "--template", "sandbox", env=ENV)
    assert created.returncode == 0, created.stdout + created.stderr
    return tmp_path / "demo"


def _run(root: Path, *extra: str):
    result = run_agac(root, "run", "-w", WORKFLOW, "--sandbox", "--wait", *extra, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _outputs(root: Path, action: str = STEP) -> dict[str, dict]:
    shown = run_agac(root, "records", "-w", WORKFLOW, "-A", action, "--sandbox", env=ENV)
    assert shown.returncode == 0, shown.stdout + shown.stderr
    return {
        record["content"]["source"]["ticket_id"]: record["content"][action]
        for record in json.loads(shown.stdout)
    }


def test_each_ticket_retrieves_the_article_that_answers_it(project):
    _run(project)

    outputs = _outputs(project)

    top = {ticket: (output["matches"] or [{}])[0] for ticket, output in outputs.items()}
    assert top["T-1001"]["title"] == "Billing > Duplicate charges"
    assert top["T-1001"]["id"] == "knowledge/help_center/billing.md#1"
    assert top["T-1004"]["title"] == "Account access > Change your email address"
    assert top["T-1005"]["origin"] == "knowledge/help_center/refunds.md"
    assert len({output["index"] for output in outputs.values()}) == 1


def test_a_ticket_filtered_upstream_never_reaches_the_step(project):
    _run(project)

    # The step takes draft_reply's dependencies, so classify's guard filters the two spam
    # tickets before the step, as it does before draft_reply.
    assert sorted(_outputs(project)) == ["T-1001", "T-1002", "T-1004", "T-1005"]


def test_a_later_action_in_a_route_branch_searches_only_for_the_records_of_its_branch(
    project,
):
    workflow = project / "agent_workflow/support_desk/agent_config/support_desk.yml"
    workflow.write_text(
        workflow.read_text()
        + """
  - name: billing_note
    dependencies: [billing_team]
    intent: "Write a note for the billing team"
    prompt: "{{ billing_team.team }}: {% for m in retrieve.policy.matches %}{{ m.id }}{% endfor %}"
    schema: {note: string}
    context_scope:
      observe: [billing_team.*]
      retrieve:
        policy: {from: help_center, query: source.text}
"""
    )
    _run(project)

    billing = _outputs(project, "billing_team")
    assert len(billing) == 2
    assert sorted(_outputs(project, "billing_note__policy")) == sorted(billing)


def test_an_edited_article_warns_the_step_and_rerun_answers_it_again(project):
    _run(project)
    (project / "knowledge/help_center/billing.md").write_text(
        "# Billing\n\n## Duplicate charges\n\nIf you were charged twice, we refund it in a week.\n"
    )

    warned = _run(project)

    assert (
        f"reply_round_iter1__draft_reply: retrieve 'help' ({STEP}): knowledge base "
        f"'help_center' changed since it answered; run again with --rerun {STEP}"
    ) in " ".join((warned.stdout + warned.stderr).split())
    again = _run(project, "--rerun", STEP)
    assert "knowledge base 'help_center' changed" not in again.stdout + again.stderr
    assert "in a week" in _outputs(project)["T-1001"]["matches"][0]["text"]

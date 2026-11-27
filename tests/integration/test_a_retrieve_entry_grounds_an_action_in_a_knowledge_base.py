"""The starter template grounds its reply in help articles: draft_reply retrieves for each ticket.

The retrieve entry ``help`` of ``draft_reply`` (in the ``reply_round`` loop) searches the
``help_center`` knowledge base with ``source.text``, so the search reads real ticket text in a
sandbox run. Its step in the first round is ``reply_round_iter1__draft_reply__help``.
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


def _outputs(root: Path) -> dict[str, dict]:
    shown = run_agac(root, "records", "-w", WORKFLOW, "-A", STEP, "--sandbox", env=ENV)
    assert shown.returncode == 0, shown.stdout + shown.stderr
    return {
        record["content"]["source"]["ticket_id"]: record["content"][STEP]
        for record in json.loads(shown.stdout)
    }


def test_each_ticket_retrieves_the_article_that_answers_it(project):
    _run(project)

    outputs = _outputs(project)

    top = {ticket: (output["matches"] or [{}])[0] for ticket, output in outputs.items()}
    assert top["T-1001"]["title"] == "Billing > Duplicate charges"
    assert top["T-1001"]["id"] == "knowledge/help_center/billing.md#1"
    # The spam ticket is searched too: the step reads only source.text, so it runs before
    # classify's guard filters the ticket.
    assert top["T-1003"]["title"] == "Account access > Suspicious messages"
    assert top["T-1004"]["title"] == "Account access > Change your email address"
    assert top["T-1005"]["origin"] == "knowledge/help_center/refunds.md"
    # T-1006 shares no word with the articles once stopwords are dropped and words stemmed.
    assert outputs["T-1006"]["matches"] == []
    assert outputs["T-1006"]["count"] == 0
    assert len({output["index"] for output in outputs.values()}) == 1


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

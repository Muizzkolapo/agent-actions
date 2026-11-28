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


PRODUCT_TOOL = """
from typing import Any

from agent_actions import udf_tool


@udf_tool
def pick_product(data: Any, *args: Any) -> dict:
    queue = data["read_ticket"]["queue"]
    return {"queue": queue, "product": "billing"} if queue == "billing" else {"queue": queue}
"""


SKIP_ON_SUPPORT = """
    guard:
      condition: 'read_ticket.queue == "billing"'
      on_false: skip"""


@pytest.mark.parametrize(
    ("where_ref", "guard"),
    [
        # The tool leaves the optional schema field out for a support ticket.
        ("pick_product.product", ""),
        # The guard skips the tool for a support ticket: its namespace is null.
        ("pick_product.product", SKIP_ON_SUPPORT),
        # Only the staged ticket T-1001 has a product field.
        ("source.product", ""),
    ],
)
def test_a_where_ref_the_record_lacks_matches_nothing_and_never_fails_it(
    project, where_ref, guard
):
    (project / "tools/support_desk/product_tools.py").write_text(PRODUCT_TOOL)
    staged = project / "agent_workflow/support_desk/agent_io/staging/tickets.json"
    tickets = json.loads(staged.read_text())
    tickets[0]["product"] = "billing"
    staged.write_text(json.dumps(tickets))
    (project / "schema/support_desk/product.yml").write_text(
        "name: product\nfields:\n  - {id: queue, type: string, required: true}\n"
        "  - {id: product, type: string, required: false}\n"
    )
    (project / "knowledge/faq.json").write_text(
        json.dumps(
            [
                {"id": "f1", "text": "A charge twice is refunded.", "product": "billing"},
                {"id": "f2", "text": "A charge on the app is checked.", "product": "app"},
            ]
        )
    )
    config = project / "agent_actions.yml"
    config.write_text(
        config.read_text()
        + "  faq:\n    sources:\n"
        + "      - {path: knowledge/faq.json, text: text, id: id, metadata: [product]}\n"
    )
    workflow = project / "agent_workflow/support_desk/agent_config/support_desk.yml"
    workflow.write_text(
        workflow.read_text()
        + """
  - name: pick_product
    dependencies: [read_ticket]
    kind: tool
    impl: pick_product
    intent: "Pick the product of a billing ticket"
    schema: product__GUARD__
    context_scope:
      observe: [read_ticket.queue]

  - name: faq_note
    dependencies: [pick_product]
    intent: "Write a note from the FAQ"
    prompt: "{% for m in retrieve.faq.matches %}{{ m.id }}{% endfor %}"
    schema: {note: string}
    context_scope:
      observe: ["pick_product.product?"]
      retrieve:
        faq: {from: faq, query: source.text, where: {product: __WHERE__}}
""".replace("__GUARD__", guard).replace("__WHERE__", where_ref)
    )
    _run(project)

    outputs = _outputs(project, "faq_note__faq")
    assert len(outputs) == 6
    assert [m["id"] for m in outputs["T-1001"]["matches"]] == ["f1"]
    assert outputs["T-1002"]["matches"] == []

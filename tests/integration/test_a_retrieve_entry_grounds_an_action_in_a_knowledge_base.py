"""The starter template with a knowledge base: classify retrieves help articles for each ticket."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from tests._support.agac_cli import run_agac

pytestmark = pytest.mark.skip(
    reason="needs agent_actions.knowledge from the knowledge base stream; the integration "
    "step removes this marker"
)

TEMPLATE = Path(__file__).parents[2] / "agent_actions/cli/project_templates/sandbox"
WORKFLOW = "support_desk"
ARTICLES = {
    "billing.md": "# Billing\n\n## Charged twice\n\nIf you were charged twice for one invoice, "
    "we refund the second charge within five days.\n",
    "app.md": "# App\n\n## The app closes\n\nIf the app closes when you upload a photo, "
    "install the latest version.\n",
    "account.md": "# Account\n\n## Change your email\n\nTo change the email address of your "
    "account, open Settings and choose Email.\n",
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    shutil.copytree(TEMPLATE, root)
    config = root / "agent_actions.yml"
    config.write_text(
        config.read_text().replace("__PROJECT_NAME__", "demo")
        + "knowledge:\n  help_center:\n    sources: [knowledge/help_center/*.md]\n"
    )
    folder = root / "knowledge" / "help_center"
    folder.mkdir(parents=True)
    for name, text in ARTICLES.items():
        (folder / name).write_text(text)
    workflow = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    data = yaml.safe_load(workflow.read_text())
    classify = next(a for a in data["actions"] if a.get("name") == "classify")
    classify["context_scope"]["retrieve"] = {
        "help": {"from": "help_center", "query": "read_ticket.text", "top_k": 1}
    }
    workflow.write_text(yaml.safe_dump(data, sort_keys=False))
    return root


def _run(root: Path, *extra: str):
    result = run_agac(root, "run", "-w", WORKFLOW, "--sandbox", "--wait", *extra)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _top_origins(root: Path) -> dict[str, str]:
    shown = run_agac(root, "records", "-w", WORKFLOW, "-A", "classify__help", "--sandbox")
    assert shown.returncode == 0, shown.stdout + shown.stderr
    origins = {}
    for record in json.loads(shown.stdout):
        output = record["content"]["classify__help"]
        ticket = record["content"]["read_ticket"]["ticket_id"]
        origins[ticket] = output["matches"][0]["origin"] if output["matches"] else ""
    return origins


def test_each_ticket_retrieves_the_article_that_answers_it(project):
    _run(project)

    origins = _top_origins(project)

    assert origins["T-1001"].endswith("billing.md")
    assert origins["T-1002"].endswith("app.md")
    assert origins["T-1004"].endswith("account.md")
    assert "T-1003" not in origins  # spam is filtered before the step, as before classify


def test_an_edited_article_warns_the_step_and_rerun_answers_it_again(project):
    _run(project)
    (project / "knowledge/help_center/billing.md").write_text(
        "# Billing\n\nRefunds take a week.\n"
    )

    warned = _run(project)

    assert (
        "classify: retrieve 'help' (classify__help): knowledge base 'help_center' changed "
        "since it answered; run again with --rerun classify__help"
    ) in " ".join((warned.stdout + warned.stderr).split())
    again = _run(project, "--rerun", "classify")
    assert "knowledge base 'help_center' changed" not in again.stdout + again.stderr

"""An online action's calls are reported per kind by `agac usage` and in the run history.

Through the CLI against the mock provider: two records, one action, a judged rule with five
votes. The action's own calls are `main`, the judge's are `judge`. The mock's online client
reports no tokens, so the calls are what is counted here; the token sums are proven where a
vendor's response carries them.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "usage_online"
VOTES = 5
RECORDS = 2

_CONFIG = f"""\
name: {WORKFLOW}
description: "A judged rule on an online action"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: usage_online_summary
    prompt: $usage_online.Summarize
    context_scope: {{ observe: [source.page_content] }}
    expect:
      repair: none
      expectations:
        - id: grounded
          type: llm_judge
          field: summary
          params: {{ rule: "The summary only states what the page says.", votes: {VOTES} }}
"""

_SUMMARY = """\
name: usage_online_summary
fields:
  - id: summary
    type: string
additionalProperties: true
"""

_PROMPTS = """\
{prompt Summarize}
Summarise this.
## PAGE
{{ source.page_content }}
{end_prompt}
"""


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_CONFIG)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps(
            [{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(1, RECORDS + 1)]
        )
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "usage_online_summary.yml").write_text(_SUMMARY)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run(project: Path, *args: str) -> None:
    result = run_agac(project, "run", "-a", WORKFLOW, *args)
    assert result.returncode == 0, result.stdout + result.stderr


def _report(project: Path) -> dict:
    result = run_agac(project, "usage", "-a", WORKFLOW, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _calls(report: dict) -> list[tuple[str, bool, int]]:
    return [
        (row["kind"], row["batch"], row["calls"])
        for row in report["actions"]["summarize"]["by_kind"]
    ]


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    root = _project(tmp_path_factory.mktemp("usage_online"))
    _run(root, "--fresh")
    return root


def test_the_action_s_own_calls_and_its_judge_s_votes_are_reported_apart(project):
    assert _calls(_report(project)) == [
        ("main", False, RECORDS),
        ("judge", False, RECORDS * VOTES),
    ]


def test_the_run_history_holds_the_same_calls_for_the_action_and_the_run(project):
    (run,) = json.loads((project / "artefact" / "runs.json").read_text())["executions"]

    usage = run["actions"]["summarize"]["usage"]
    assert [(row["kind"], row["calls"]) for row in usage["by_kind"]] == [
        ("main", RECORDS),
        ("judge", RECORDS * VOTES),
    ]
    assert usage["calls"] == run["usage"]["calls"] == RECORDS + RECORDS * VOTES
    assert _report(project)["runs"] == [run["id"]]


def test_a_run_that_finds_the_action_done_adds_no_call(project, tmp_path):
    again = tmp_path / "project"
    shutil.copytree(project, again)

    _run(again)

    report = _report(again)
    assert _calls(report) == _calls(_report(project))
    assert len(report["runs"]) == 1


def test_a_fresh_run_starts_the_sum_again(project, tmp_path):
    again = tmp_path / "project"
    shutil.copytree(project, again)

    _run(again, "--fresh")

    report = _report(again)
    assert _calls(report) == [("main", False, RECORDS), ("judge", False, RECORDS * VOTES)]
    assert len(report["runs"]) == 1
    assert report["runs"] != _report(project)["runs"]

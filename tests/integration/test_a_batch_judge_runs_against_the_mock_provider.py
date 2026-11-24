"""A batch action's judged rule runs as a judge batch, end to end through `agac run` (1814).

Against the agac provider mock: the action's main batch, then one judge batch
for its judge calls, and no judge call online. Each record ships the verdict the
mock's judge gave it.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_PAUSED
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "judged_in_batch"

_CONFIG = """\
name: judged_in_batch
description: "A judged rule on a batch action"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: batch
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: summarize
    intent: "Summarise"
    schema: judged_in_batch_summary
    prompt: $judged_in_batch.Summarize
    context_scope: { observe: [source.page_content] }
    expect:
      repair: none
      expectations:
        - id: grounded
          type: llm_judge
          field: summary
          params: { rule: "The summary only states what the page says.", votes: 3 }
"""

_SUMMARY = """\
name: judged_in_batch_summary
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
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in (1, 2)])
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "judged_in_batch_summary.yml").write_text(_SUMMARY)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> list[str]:
    outputs = []
    for attempt in range(8):
        args = ("--fresh",) if attempt == 0 else ()
        result = run_agac(project, "run", "-a", WORKFLOW, *args)
        output = result.stdout + result.stderr
        outputs.append(output)
        if result.returncode == EXIT_PAUSED:
            assert "run again" in output, output
            continue
        assert result.returncode == 0, output
        assert "run again" not in output, output
        return outputs
    pytest.fail(f"the workflow never stopped asking to be run again:\n{outputs[-1]}")


@pytest.fixture
def finished(tmp_path):
    project = _project(tmp_path)
    return project, _run_to_the_end(project)


def _events(project: Path) -> list[dict]:
    logs = project / "agent_workflow" / WORKFLOW / "agent_io" / "logs"
    return [
        json.loads(line)
        for path in sorted(logs.glob("events*.json"))
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _verdicts(project: Path) -> list[dict]:
    from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    backend = SQLiteBackend(str(db), WORKFLOW)
    backend.initialize()
    return [
        row["content"]["summarize"]["expect"]
        for row in backend.read_target("summarize", "pages.json")
    ]


def test_the_main_batch_and_one_judge_batch_go_out_and_no_judge_call_online(finished):
    project, outputs = finished
    events = _events(project)

    submitted = [
        int(m.group(1))
        for e in events
        if (m := re.fullmatch(r"Mock batch \S+ submitted: (\d+) tasks", e.get("message", "")))
    ]
    assert sorted(submitted) == [2, 2 * 3], "expected the main batch and one judge request per vote"
    assert any("submitted as pages.json_judge_1" in e.get("message", "") for e in events)
    online = [e for e in events if e.get("event_type") == "LLMRequestEvent"]
    assert online == [], f"{len(online)} judge call(s) went online"
    assert len(outputs) == 3, "a pass for the main batch, one for the judge batch, one to finish"


def test_each_record_ships_the_verdict_its_votes_gave(finished):
    project, _outputs = finished
    verdicts = _verdicts(project)

    assert len(verdicts) == 2
    for verdict in verdicts:
        (outcome,) = verdict["outcomes"]
        assert outcome["type"] == "llm_judge"
        assert re.match(r"[0-3]/3 judge votes passed", outcome["detail"]), outcome["detail"]

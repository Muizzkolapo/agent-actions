"""`agac run --sandbox` answers every LLM action with the offline mock and keeps its output apart.

The workflow names a real vendor and no key is set. The sandbox run completes, its tool
action runs its own code, its HITL review approves, and what it writes goes to the sandbox
store and folder. The store, target folder, logs and status file of a real run are left
as they were, and a real run never sees a sandbox run's work as its own. A retry and
each read command given ``--sandbox`` read the sandbox store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "sandboxed"
ROWS = [{"text": "calm sea"}, {"text": "high wind"}]

CONFIG = """name: sandboxed
description: "One tool action, one LLM action, one review"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: {vendor}
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: shout
    kind: tool
    intent: "Shout"
    schema: shout_output
    impl: shout_text
    context_scope: {{ observe: [source.text] }}
  - name: summarize
    dependencies: [shout]
    intent: "Summarize"
    schema: summary_output
    prompt: $sandboxed.Summarize
    context_scope: {{ observe: [shout.loud] }}
    expect:
      repair: none
      expectations:
        - id: tone_is_known
          type: accepted_values
          field: tone
          params: {{values: [calm, stormy]}}
{review}"""

REVIEW = """  - name: review
    kind: hitl
    dependencies: [summarize]
    intent: "Review"
    hitl: { port: 3999, instructions: "Review the summaries", timeout: 5 }
    context_scope: { observe: [summarize.summary] }
"""

PROMPTS = """# sandboxed - prompt store

{prompt Summarize}
Summarise this text and name its tone.
{{ shout.loud }}
```json
{"summary": "...", "tone": "calm|stormy"}
```
{end_prompt}
"""

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def shout_text(data: Any, *args) -> list[dict]:
    return [{"loud": str(((data or {}).get("source") or {}).get("text", "")).upper()}]
"""

SCHEMAS = {
    "shout_output": "name: shout_output\nfields:\n  - id: loud\n    type: string\n",
    "summary_output": (
        "name: summary_output\nfields:\n  - id: summary\n    type: string\n"
        "  - id: tone\n    type: string\n"
    ),
}


def _project(base: Path, vendor: str, review: bool, run_mode: str = "online") -> Path:
    root = base / "project"
    workflow_dir = root / "agent_workflow" / WORKFLOW
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\n"
        'tool_path: ["tools"]\nschema_path: schema\n'
    )
    (workflow_dir / "agent_config" / f"{WORKFLOW}.yml").write_text(
        CONFIG.format(vendor=vendor, review=REVIEW if review else "", run_mode=run_mode)
    )
    (workflow_dir / "agent_io" / "staging" / "rows.json").write_text(json.dumps(ROWS))
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    (root / "tools" / WORKFLOW / "sandbox_shout.py").write_text(TOOLS)
    for name, text in SCHEMAS.items():
        (root / "schema" / WORKFLOW / f"{name}.yml").write_text(text)
    return root


def _io(root: Path) -> Path:
    return root / "agent_workflow" / WORKFLOW / "agent_io"


def _agac(root: Path, *args: str):
    result = run_agac(root, *args, env={"OPENAI_API_KEY": ""})
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _records(root: Path, action: str, *flags: str) -> list[dict]:
    shown = _agac(root, "records", "-w", WORKFLOW, "-A", action, *flags)
    return json.loads(shown.stdout)


def _real_output(root: Path) -> dict[str, bytes]:
    """Each file a real run writes, by path."""
    io = _io(root)
    files = [io / ".agent_status.json", io / "store" / f"{WORKFLOW}.db"]
    files += sorted(p for p in (io / "logs").rglob("*") if p.is_file())
    return {str(p.relative_to(io)): p.read_bytes() for p in files if p.exists()}


@pytest.fixture
def openai_project(tmp_path):
    return _project(tmp_path, "openai", review=True)


@pytest.fixture
def mock_project(tmp_path):
    return _project(tmp_path, "agac-provider", review=False)


def test_a_workflow_on_a_real_vendor_runs_with_no_key(openai_project):
    result = _agac(openai_project, "run", "-w", WORKFLOW, "--sandbox")

    assert "SANDBOX" in result.stdout
    io = _io(openai_project)
    statuses = json.loads((io / "sandbox" / ".agent_status.json").read_text())
    assert {name: entry["status"] for name, entry in statuses.items()} == {
        "shout": "completed",
        "summarize": "completed",
        "review": "completed",
    }
    assert (io / "store" / f"{WORKFLOW}.sandbox.db").is_file()


def test_a_sandbox_run_writes_nothing_a_real_run_reads(openai_project):
    _agac(openai_project, "run", "-w", WORKFLOW, "--sandbox")

    io = _io(openai_project)
    assert not (io / "store" / f"{WORKFLOW}.db").exists()
    assert not (io / ".agent_status.json").exists()
    assert not (io / "target").exists()
    assert not (io / "logs").exists()
    assert (io / "sandbox" / "logs").is_dir()


def test_the_tool_runs_its_code_and_the_review_approves(openai_project):
    _agac(openai_project, "run", "-w", WORKFLOW, "--sandbox")

    shouted = _records(openai_project, "shout", "--sandbox")
    assert sorted(r["content"]["shout"]["loud"] for r in shouted) == ["CALM SEA", "HIGH WIND"]
    summaries = _records(openai_project, "summarize", "--sandbox")
    assert {r["content"]["summarize"]["tone"] for r in summaries} <= {"calm", "stormy"}
    reviewed = _records(openai_project, "review", "--sandbox")
    assert {r["content"]["review"]["hitl_status"] for r in reviewed} == {"approved"}


def test_status_and_records_read_the_store_they_are_told_to(openai_project):
    _agac(openai_project, "run", "-w", WORKFLOW, "--sandbox")

    sandbox = json.loads(
        _agac(openai_project, "status", "-w", WORKFLOW, "--sandbox", "--json").stdout
    )
    assert sandbox["run_status"] == "SUCCESS"
    real = json.loads(_agac(openai_project, "status", "-w", WORKFLOW, "--json").stdout)
    assert real["run_status"] is None
    refused = run_agac(openai_project, "records", "-w", WORKFLOW, "-A", "shout")
    assert refused.returncode != 0
    real_store = _io(openai_project) / "store" / f"{WORKFLOW}.db"
    assert f"No store for workflow '{WORKFLOW}' at {real_store}" in refused.stderr


def test_a_sandbox_run_leaves_a_real_runs_files_as_they_were(mock_project):
    _agac(mock_project, "run", "-w", WORKFLOW)
    before = _real_output(mock_project)
    assert ".agent_status.json" in before

    _agac(mock_project, "run", "-w", WORKFLOW, "--sandbox", "--fresh")

    assert _real_output(mock_project) == before


def test_a_real_run_after_a_sandbox_run_answers_every_action(mock_project):
    _agac(mock_project, "run", "-w", WORKFLOW, "--sandbox")

    _agac(mock_project, "run", "-w", WORKFLOW)

    io = _io(mock_project)
    statuses = json.loads((io / ".agent_status.json").read_text())
    assert {entry["status"] for entry in statuses.values()} == {"completed"}
    assert len(_records(mock_project, "summarize")) == len(ROWS)


def test_clean_all_removes_the_sandbox_output(openai_project):
    _agac(openai_project, "run", "-w", WORKFLOW, "--sandbox")

    _agac(openai_project, "clean", "-w", WORKFLOW, "--all", "--force")

    io = _io(openai_project)
    assert not (io / "sandbox").exists()
    assert not (io / "store" / f"{WORKFLOW}.sandbox.db").exists()


def test_a_batch_action_is_answered_by_the_mock_batch(tmp_path):
    root = _project(tmp_path, "openai", review=False, run_mode="batch")

    _agac(root, "run", "-w", WORKFLOW, "--sandbox", "--wait", "--poll", "1")

    io = _io(root)
    assert (io / "sandbox" / "target" / "summarize" / "batch").is_dir()
    assert not (io / "target").exists()
    assert len(_records(root, "summarize", "--sandbox")) == len(ROWS)


def test_inspect_shows_the_mock_in_place_of_the_vendor(openai_project):
    result = _agac(openai_project, "inspect", "-w", WORKFLOW, "--sandbox", "action", "summarize")

    assert "SANDBOX" in result.stdout + result.stderr
    assert "answered by the sandbox mock" in result.stdout


FLAKY_TOOLS = """from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def shout_text(data: Any, *args) -> list[dict]:
    text = str(((data or {}).get("source") or {}).get("text", ""))
    if Path("wind.fails").exists() and "wind" in text:
        raise ValueError("no wind today")
    return [{"loud": text.upper()}]
"""


def _counts(root: Path, action: str) -> dict[str, int]:
    report = json.loads(_agac(root, "dispositions", "-w", WORKFLOW, "--sandbox", "--json").stdout)
    return next(entry for entry in report["actions"] if entry["name"] == action)["counts"]


def test_retry_repairs_the_failed_records_of_a_sandbox_run(openai_project):
    (openai_project / "tools" / WORKFLOW / "sandbox_shout.py").write_text(FLAKY_TOOLS)
    marker = openai_project / "wind.fails"
    marker.touch()
    failed = run_agac(
        openai_project, "run", "-w", WORKFLOW, "--sandbox", env={"OPENAI_API_KEY": ""}
    )
    assert failed.returncode != 0
    assert _counts(openai_project, "shout")["failed"] == 1
    marker.unlink()

    _agac(openai_project, "retry", "-w", WORKFLOW, "--sandbox")

    assert _counts(openai_project, "shout")["failed"] == 0
    shouted = _records(openai_project, "shout", "--sandbox")
    assert sorted(r["content"]["shout"]["loud"] for r in shouted) == ["CALM SEA", "HIGH WIND"]
    io = _io(openai_project)
    assert (io / "store" / f"{WORKFLOW}.sandbox").is_dir(), "the retry manifest left the sandbox"
    for real in (
        f"store/{WORKFLOW}.db",
        f"store/{WORKFLOW}",
        "target",
        "logs",
        ".agent_status.json",
    ):
        assert not (io / real).exists(), f"a sandbox retry wrote {real}"


@pytest.fixture(scope="module")
def sandbox_only(tmp_path_factory):
    """A project that only a sandbox run has run."""
    root = _project(tmp_path_factory.mktemp("read"), "openai", review=False)
    _agac(root, "run", "-w", WORKFLOW, "--sandbox")
    return root


def test_traces_reads_the_sandbox_store(sandbox_only):
    shown = _agac(sandbox_only, "traces", "-w", WORKFLOW, "-A", "summarize", "--sandbox")
    assert shown.stdout.count("=== summarize record") == len(ROWS)
    assert "(agac-provider gpt-4o-mini)" in shown.stdout


def test_usage_reads_the_sandbox_store(sandbox_only):
    shown = _agac(sandbox_only, "usage", "-w", WORKFLOW, "--sandbox")
    row = next(line for line in shown.stdout.splitlines() if "summarize" in line)
    assert "agac-mock" in row
    assert f" {len(ROWS)} " in row


def test_preview_reads_the_sandbox_store(sandbox_only):
    shown = _agac(sandbox_only, "preview", "-w", WORKFLOW, "--sandbox")
    actions = {line.split("│")[2].strip() for line in shown.stdout.splitlines() if "│" in line}
    assert actions == {"shout", "summarize"}


def test_dispositions_reads_the_sandbox_store(sandbox_only):
    assert _counts(sandbox_only, "summarize")["success"] == len(ROWS)


def test_expect_report_reads_the_sandbox_store(sandbox_only):
    shown = _agac(sandbox_only, "expect", "report", "-w", WORKFLOW, "--sandbox")
    assert f"summarize  {len(ROWS)}/{len(ROWS)} records passed" in shown.stdout
    assert "tone_is_known" in shown.stdout

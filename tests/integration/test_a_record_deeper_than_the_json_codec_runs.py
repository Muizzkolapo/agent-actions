"""A record nested deeper than the JSON codec can recurse runs, retries and is stored whole.

The C JSON codec recurses once per nesting level: on Python 3.11 it gives up about 1000
levels down. Reading staging, storing the record and writing the target all went through
it, so a run on such a record failed before its identity was even derived. ``DEPTH`` is far
past the codec's limit on any interpreter, so this reproduces whatever Python runs it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
DEPTH = 20_000
LEAF = "leaf at the bottom"
ENV = {
    "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0",
    "OLLAMA_API_KEY": "not-used",
    "OPENAI_API_KEY": "sk-not-used",
    "AGAC_RECORD_LIMIT": "",
}


def _project(tmp_path: Path, workflow: str, run_mode: str, observe_deep: bool = False) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    config = root / "agent_workflow" / workflow / "agent_config" / f"{workflow}.yml"
    text = config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
    text = text.replace("run_mode: online", f"run_mode: {run_mode}")
    text = text.replace("run_mode: batch", f"run_mode: {run_mode}")
    if observe_deep:
        anchor = "observe: [source.page_content]"
        assert text.count(anchor) == 1
        text = text.replace(anchor, "observe: [source.page_content, source.deep]")
    config.write_text(text)
    staging = root / "agent_workflow" / workflow / "agent_io" / "staging"
    for old in staging.glob("*.json"):
        old.unlink()
    deep = "[" * DEPTH + json.dumps(LEAF) + "]" * DEPTH
    (staging / "pages.json").write_text(
        '[{"page_id": "p0", "page_content": "page 0", "deep": ' + deep + "}, "
        '{"page_id": "p1", "page_content": "page 1"}]'
    )
    return root


def _agac(root: Path, *args: str):
    return run_agac(root, *args, env=ENV)


def _run_to_completion(root: Path, workflow: str) -> list:
    ran = []
    for _ in range(4):
        result = _agac(root, "run", "-a", workflow, *(["--fresh"] if not ran else []))
        ran.append(result)
        if result.returncode != 0 or "run again" not in result.stdout + result.stderr:
            break
    return ran


def _stored(root: Path, workflow: str, action: str) -> tuple[dict[str, str], list[dict]]:
    paths = ProjectPathsFactory.create_project_paths(
        workflow, workflow, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=workflow)
    backend.initialize()
    try:
        dispositions = {
            row["record_id"]: row["disposition"]
            for row in backend.get_disposition(action)
            if row["record_id"] != NODE_LEVEL_RECORD_ID
        }
        return dispositions, backend.read_target(action, "pages.json")
    finally:
        backend.close()


def _depth_and_leaf(node) -> tuple[int, object]:
    depth = 0
    while isinstance(node, list) and len(node) == 1:
        node = node[0]
        depth += 1
    return depth, node


def _deep_value_of(rows: list[dict]):
    held = [r["content"]["source"]["deep"] for r in rows if "deep" in r["content"]["source"]]
    assert len(held) == 1
    return held[0]


def _output(result) -> str:
    return (result.stdout + result.stderr)[-3000:]


@pytest.mark.parametrize(
    "workflow, action, run_mode",
    [
        ("tool_action", "flatten", "online"),
        ("batch_field_rules", "summarize", "online"),
        ("batch_field_rules", "summarize", "batch"),
    ],
)
def test_the_run_completes_and_stores_the_record_whole(tmp_path, workflow, action, run_mode):
    root = _project(tmp_path, workflow, run_mode)

    ran = _run_to_completion(root, workflow)

    assert all(r.returncode == 0 for r in ran), [_output(r) for r in ran]
    dispositions, rows = _stored(root, workflow, action)
    assert sorted(dispositions.values()) == ["success", "success"]
    assert _depth_and_leaf(_deep_value_of(rows)) == (DEPTH, LEAF)

    retried = _agac(root, "retry", "-a", workflow)
    assert retried.returncode == 0, _output(retried)
    again = _agac(root, "run", "-a", workflow)
    assert again.returncode == 0, _output(again)
    assert sorted(_stored(root, workflow, action)[0].values()) == ["success", "success"]


def test_a_tool_that_observes_the_deep_field_runs_and_a_retry_reaches_the_record_that_failed(
    tmp_path,
):
    """p1 has no ``deep`` field, so observing it fails p1 alone, as it would at any depth.

    The retry looks for repeat chains across every stored source row with SQLite's JSON
    functions, which refuse a row 1000 levels deep and used to fail the whole query.
    """
    root = _project(tmp_path, "tool_action", "online", observe_deep=True)

    ran = _agac(root, "run", "-a", "tool_action", "--fresh")

    assert ran.returncode == 0, _output(ran)
    first = _stored(root, "tool_action", "flatten")[0]
    assert sorted(first.values()) == ["failed", "success"]

    retried = _agac(root, "retry", "-a", "tool_action")

    assert retried.returncode == 0, _output(retried)
    assert "malformed JSON" not in retried.stdout + retried.stderr
    assert _stored(root, "tool_action", "flatten")[0] == first

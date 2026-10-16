"""A record nested hundreds of levels deep runs through a batch action.

`copy.deepcopy` recurses once per level, so it fails on a record about 500 levels deep.
Under `run_mode: batch` a record is copied while its task is prepared and again while
its results are collected, and either failed the run, every later run with it.
Depths to about 400 completed, which is why this went unseen.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ACTION = "summarize"


def _nested(depth: int) -> list:
    node: list = []
    for _ in range(depth):
        node = [node]
    return node


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def _record_dispositions(root: Path) -> dict[str, str]:
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return {
            row["record_id"]: row["disposition"]
            for row in backend.get_disposition(ACTION)
            if row["record_id"] != NODE_LEVEL_RECORD_ID
        }
    finally:
        backend.close()


def _project(tmp_path, monkeypatch, depth: int) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    for config in root.glob("agent_workflow/*/agent_config/*.yml"):
        config.write_text(
            config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
        )
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(
        json.dumps(
            [
                {"page_id": "p0", "page_content": "page 0", "deep": _nested(depth)},
                {"page_id": "p1", "page_content": "page 1"},
            ]
        )
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used")
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    return root


def _run_to_completion() -> list:
    ran = []
    for _ in range(4):
        result = _invoke("run", "-a", WORKFLOW, *(["--fresh"] if not ran else []))
        ran.append(result)
        if result.exit_code != 0 or "run again" not in result.output:
            break
    return ran


class TestARecordNestedDeeply:
    @pytest.mark.parametrize("depth", [400, 600, 2000])
    def test_every_run_completes_and_every_record_is_answered(self, tmp_path, monkeypatch, depth):
        root = _project(tmp_path, monkeypatch, depth)

        ran = _run_to_completion()

        assert all(r.exit_code == 0 for r in ran), [r.output for r in ran]
        assert sorted(_record_dispositions(root).values()) == ["success", "success"]

    def test_a_run_after_it_still_completes(self, tmp_path, monkeypatch):
        root = _project(tmp_path, monkeypatch, 600)
        ran = _run_to_completion()
        assert all(r.exit_code == 0 for r in ran), [r.output for r in ran]

        again = _invoke("run", "-a", WORKFLOW)

        assert again.exit_code == 0, again.output
        assert sorted(_record_dispositions(root).values()) == ["success", "success"]

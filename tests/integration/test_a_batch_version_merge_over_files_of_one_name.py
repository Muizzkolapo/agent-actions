"""A batch version merge sends a top-level file and a nested file of one name apart.

The merge reads its own target, where the correlated input of both files is already
stored, and its dependencies name its versions by their base, which stores nothing.
Driven through `agac run` with the mock provider.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parents[2] / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
MERGE = "merge_direct"

CONFIG = """name: map_reduce_fanin_check
description: "batch version merge over files of one name"
version: "1.0.0"

defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source:
    type: local
    folder: ./staging
    file_type: [json]

actions:
  - name: stage_items
    kind: tool
    impl: stage_items
    intent: "Stage"
    schema: { item_id: string, text: string }
    context_scope:
      observe: [source.item_id, source.text]

  - name: vote_direct
    kind: tool
    impl: cast_vote_direct
    dependencies: [stage_items]
    intent: "Vote"
    versions: { param: voter_id, range: [1, 2] }
    schema: { vote: string, voted_item: string }
    context_scope:
      observe: [stage_items.*]

  - name: merge_direct
    dependencies: [vote_direct]
    run_mode: batch
    intent: "Merge"
    version_consumption: { source: vote_direct, pattern: merge }
    prompt: "Merge the votes into one summary."
    schema: { summary: string }
    context_scope:
      observe: [vote_direct.*]
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG)
    staging = workflow / "agent_io" / "staging"
    (staging / "items.json").write_text(
        json.dumps([{"item_id": "top1", "text": "top one"}, {"item_id": "top2", "text": "two"}])
    )
    (staging / "sub").mkdir()
    (staging / "sub" / "items.json").write_text(
        json.dumps([{"item_id": "sub1", "text": "sub one"}, {"item_id": "sub2", "text": "two"}])
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used")
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    return root


def _run(*extra):
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "-u", "tools", *extra])
    assert result.exit_code == 0, result.output
    return result


def _store(root):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def test_a_nested_file_of_a_top_level_name_is_its_own_batch_and_answered(project):
    _run("--fresh")
    _run()

    backend = _store(project)
    try:
        registry = sorted(BatchRegistryManager(backend, MERGE).get_all_jobs())
        states = {
            name: sorted(row.get("_state") for row in backend._read_target_raw(MERGE, name))
            for name in backend.list_target_files(MERGE)
        }
        names = json.loads(backend.load_metadata(f"batch_file_names:{MERGE}") or "{}")
    finally:
        backend.close()

    assert registry == ["items.json", "sub/items.json"]
    assert names == {"sub/items.json": "sub/items.json"}
    assert states == {
        "items.json": ["processed", "processed"],
        "sub/items.json": ["processed", "processed"],
    }

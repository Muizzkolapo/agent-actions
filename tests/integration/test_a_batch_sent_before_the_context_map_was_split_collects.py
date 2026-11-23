"""A batch whose context map an earlier version saved whole still collects, through `agac run`.

Submission now stores a batch's context map in parts (#1865). A batch submitted before
an upgrade holds its map as one string, and the run after the upgrade collects it. It
stores the rows a batch submitted and collected by this version stores; only the mock
model's answers differ, as they differ between any two batches.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.exit_codes import EXIT_PAUSED
from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.storage import get_storage_backend
from agent_actions.utils import deep_json

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "split_map"

_CONFIG = """\
name: split_map
description: "One batch action"
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
    prompt: $split_map.Summarize
    schema: { summary: string }
    context_scope: { observe: [source.page_content] }
"""

_PROMPTS = """\
{prompt Summarize}
Summarise this page.
{{ source.page_content }}
{end_prompt}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i} text"} for i in range(6)])
    )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_CONFIG)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    monkeypatch.chdir(root)
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    return root


def _backend(project):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _submit(project) -> None:
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == EXIT_PAUSED, result.output


def _collect(project) -> list[dict]:
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])
    assert result.exit_code == 0, result.output
    backend = _backend(project)
    try:
        rows = backend.read_target("summarize", "pages.json")
    finally:
        backend.close()
    for row in rows:
        assert row["content"]["summarize"]["summary"]
        row["content"]["summarize"] = "answered"
    # Node ids are minted per run; what a row holds besides them must match.
    return [
        {
            "keys": sorted(row),
            "lineage": len(row["lineage"]),
            **{key: row[key] for key in ("source_guid", "content", "_state")},
        }
        for row in rows
    ]


def _save_the_map_whole(project) -> None:
    """Store the submitted batch's map as an earlier version stored it: one string."""
    backend = _backend(project)
    try:
        context_map = BatchContextManager.load_batch_context_map(backend, "summarize", "pages.json")
        BatchContextManager.delete_batch_context_map(backend, "summarize", "pages.json")
        backend.save_metadata(
            "batch_context:summarize:pages.json",
            deep_json.dumps(context_map, ensure_ascii=False),
        )
        assert backend.list_metadata_prefix("batch_context:summarize:") == [
            "batch_context:summarize:pages.json"
        ]
    finally:
        backend.close()


def test_a_map_saved_whole_collects_the_rows_a_split_map_collects(project):
    _submit(project)
    split = _collect(project)

    _submit(project)
    _save_the_map_whole(project)
    whole = _collect(project)

    assert len(split) == 6
    assert whole == split

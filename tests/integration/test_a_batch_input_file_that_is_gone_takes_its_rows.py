"""A batch action re-run after one of its input files was removed holds nothing for it (1258).

The run that walks the files is the one that submits; the next only collects what
was sent, and nothing is sent for a file whose input is gone. So what it stored for
that file goes when the walk ends, before collection. Driven through `agac run`
with the mock provider.
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
from tests.integration import test_a_batch_version_merge_over_files_of_one_name as version_merge

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ACTION = "summarize"
PAGES = 2
MORE = 3
MERGE_WORKFLOW = version_merge.WORKFLOW
MERGE = version_merge.MERGE


def _staging(root):
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"


def _stage(root, name, records):
    (_staging(root) / name).write_text(
        json.dumps([{"page_content": f"{name} {i}"} for i in range(records)])
    )


def _run(*extra):
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *extra])
    assert result.exit_code == 0, result.output
    return result


def _stored(root):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return {
            path: len(backend._read_target_raw(ACTION, path))
            for path in backend.list_target_files(ACTION)
        }
    finally:
        backend.close()


def _reset(root):
    """Give the action a guard that passes everything; editing it is what resets it."""
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    text = config.read_text()
    assert "    prompt: $p.Summarize\n" in text
    config.write_text(
        text.replace(
            "    prompt: $p.Summarize\n",
            "    prompt: $p.Summarize\n    guard: { condition: 'true', on_false: \"skip\" }\n",
        )
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(
        config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
    )
    shutil.rmtree(_staging(root))
    _staging(root).mkdir()
    _stage(root, "pages.json", PAGES)
    _stage(root, "more.json", MORE)
    monkeypatch.chdir(root)
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")

    _run("--fresh")
    _run()
    assert _stored(root) == {"more.json": MORE, "pages.json": PAGES}
    return root


def test_the_rows_of_a_file_that_is_gone_go_when_the_walk_submits(project):
    (_staging(project) / "more.json").unlink()
    _reset(project)

    submitted = _run()

    assert "run again" in submitted.output, "the reset did not submit a batch"
    assert _stored(project) == {"pages.json": PAGES}


def test_collecting_does_not_bring_them_back(project):
    (_staging(project) / "more.json").unlink()
    _reset(project)
    _run()

    _run()

    assert _stored(project) == {"pages.json": PAGES}


@pytest.fixture
def merged(tmp_path, monkeypatch):
    """A version merge in batch over a top-level and a nested file, answered once."""
    root = tmp_path / "project"
    shutil.copytree(
        version_merge.SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__")
    )
    workflow = root / "agent_workflow" / MERGE_WORKFLOW
    (workflow / "agent_config" / f"{MERGE_WORKFLOW}.yml").write_text(version_merge.CONFIG)
    staging = workflow / "agent_io" / "staging"
    for name in ("items.json", "sub/items.json"):
        (staging / name).parent.mkdir(parents=True, exist_ok=True)
        (staging / name).write_text(
            json.dumps([{"item_id": f"{name}-{i}", "text": f"{name} {i}"} for i in range(2)])
        )
    monkeypatch.chdir(root)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used")
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    _run_merge("--fresh")
    _run_merge()
    assert _merge_holds(root)[0] == {"items.json": 2, "sub/items.json": 2}
    return root


def _run_merge(*extra):
    result = CliRunner().invoke(cli, ["run", "-a", MERGE_WORKFLOW, "-u", "tools", *extra])
    assert result.exit_code == 0, result.output
    return result


def _merge_holds(root):
    """Rows per file the merge stores, and the files it has a batch for."""
    paths = ProjectPathsFactory.create_project_paths(
        MERGE_WORKFLOW, MERGE_WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(
        workflow_path=str(paths.io_dir.parent), workflow_name=MERGE_WORKFLOW
    )
    backend.initialize()
    try:
        rows = {
            path: len(backend._read_target_raw(MERGE, path))
            for path in backend.list_target_files(MERGE)
        }
        return rows, sorted(BatchRegistryManager(backend, MERGE).get_all_jobs())
    finally:
        backend.close()


def test_a_version_merge_does_not_send_its_own_rows_for_a_file_that_is_gone(merged):
    """It walks its own stored files, the correlated input among them; with no version
    holding the file any more, what it stored for it would be sent as its input."""
    workflow = merged / "agent_workflow" / MERGE_WORKFLOW
    (workflow / "agent_io" / "staging" / "sub" / "items.json").unlink()
    config = workflow / "agent_config" / f"{MERGE_WORKFLOW}.yml"
    config.write_text(
        config.read_text().replace(
            "    impl: stage_items\n",
            "    impl: stage_items\n    guard: { condition: 'true', on_false: \"skip\" }\n",
        )
    )

    _run_merge()
    rows, sent = _merge_holds(merged)
    assert sent == ["items.json"]
    assert list(rows) == ["items.json"]

    _run_merge()
    assert _merge_holds(merged)[0] == {"items.json": 2}

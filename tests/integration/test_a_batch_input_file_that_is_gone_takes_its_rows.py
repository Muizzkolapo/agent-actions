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
from agent_actions.storage import get_storage_backend

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ACTION = "summarize"
PAGES = 2
MORE = 3


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

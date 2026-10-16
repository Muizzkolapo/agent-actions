"""After a batch collect pass fails, `agac retry` points the way, and the way works.

A collect pass can raise an ordinary error while it reads one file's results, for
example when the provider drops the connection. The action reads `failed`, the file's
records stay `deferred`, and its finished batch stays in the registry, uncollected.
`retry` looked only for failed records, found none, and printed a green "Nothing to
retry", so nothing told the user that running the workflow again is what collects it.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.storage import get_storage_backend

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ACTION = "summarize"
RECORDS = 4


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def _backend(root: Path):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _batch_ids(root: Path) -> set[str]:
    backend = _backend(root)
    try:
        jobs = BatchRegistryManager(backend, ACTION).get_all_jobs()
        return {entry.batch_id for entry in jobs.values()}
    finally:
        backend.close()


def _record_dispositions(root: Path) -> list[str]:
    from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID

    backend = _backend(root)
    try:
        return sorted(
            row["disposition"]
            for row in backend.get_disposition(ACTION)
            if row["record_id"] != NODE_LEVEL_RECORD_ID
        )
    finally:
        backend.close()


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    for config in root.glob("agent_workflow/*/agent_config/*.yml"):
        config.write_text(
            config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
        )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\nOPENAI_API_KEY=sk-not-used\n")
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(RECORDS)])
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used")
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    return root


@pytest.fixture
def after_a_collect_error(project, monkeypatch):
    """A submitted batch whose collect pass then failed on an ordinary error."""
    submitted = _invoke("run", "-a", WORKFLOW, "--fresh")
    assert submitted.exit_code == 0, submitted.output
    assert "run again" in submitted.output

    def provider_dropped(self, *args, **kwargs):
        raise RuntimeError("the provider dropped the connection")

    with monkeypatch.context() as patched:
        patched.setattr(BatchProcessingService, "_process_single_batch_file", provider_dropped)
        failed = _invoke("run", "-a", WORKFLOW)
    assert failed.exit_code == 1, failed.output
    return project


class TestRetryAfterACollectError:
    def test_it_does_not_say_there_is_nothing_to_retry(self, after_a_collect_error):
        result = _invoke("retry", "-a", WORKFLOW)

        assert "Nothing to retry" not in result.output
        assert result.exit_code != 0, result.output

    def test_it_names_the_remedy(self, after_a_collect_error):
        result = _invoke("retry", "-a", WORKFLOW)

        assert "Collect them first" in result.output

    def test_a_dry_run_reports_the_refusal_too(self, after_a_collect_error):
        result = _invoke("retry", "-a", WORKFLOW, "--dry-run")

        assert "Nothing to retry" not in result.output
        assert "would be refused" in result.output

    def test_a_refusal_leaves_the_finished_batch_where_it_was(self, after_a_collect_error):
        before = _batch_ids(after_a_collect_error)

        _invoke("retry", "-a", WORKFLOW)

        assert _batch_ids(after_a_collect_error) == before
        assert len(before) == 1


class TestTheAdviceItGivesWorks:
    def test_running_again_collects_every_record_and_sends_no_second_batch(
        self, after_a_collect_error
    ):
        sent = _batch_ids(after_a_collect_error)
        _invoke("retry", "-a", WORKFLOW)

        for _ in range(4):
            ran = _invoke("run", "-a", WORKFLOW)
            assert ran.exit_code == 0, ran.output
            if "run again" not in ran.output:
                break

        assert _record_dispositions(after_a_collect_error) == ["success"] * RECORDS
        assert _batch_ids(after_a_collect_error) == sent

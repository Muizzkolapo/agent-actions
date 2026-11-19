"""`agac run --wait` takes a batch workflow from submission to its end in one command.

A run that submits a batch pauses and exits 4; a wrapper had to match the paused
sentence and call `agac run` again in a loop. Every run here is one `agac run` through
the CLI against the provider mock, whose batch needs a set number of status checks.
"""

import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_batch_resumes_across_runs import _records

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
PAUSED = 4


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    for config in root.glob("agent_workflow/*/agent_config/*.yml"):
        config.write_text(
            config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
        )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\nOPENAI_API_KEY=sk-not-used\n")
    return root


def _run(project, *args, checks_until_complete: int):
    result = run_agac(
        project,
        "run",
        "-a",
        WORKFLOW,
        "-u",
        "tools",
        *args,
        env={
            "AGAC_BATCH_POLLS_UNTIL_COMPLETE": str(checks_until_complete),
            "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "999",
        },
    )
    return result.returncode, result.stdout + result.stderr


# Every waiting run is bounded, so a batch that never completes fails a test, not the suite.
WAIT = ("--wait", "--poll", "0.05", "--wait-timeout", "120")


def test_a_batch_run_with_wait_ends_with_exit_0_after_the_batches_finish(project):
    code, output = _run(project, "--fresh", *WAIT, checks_until_complete=2)

    assert code == 0, output
    assert output.count("Workflow paused - batch job(s) submitted") == 2, output
    assert _records(project), "the batch was submitted but nothing was collected"


def test_without_wait_the_same_run_pauses_and_exits_4(project):
    code, output = _run(project, "--fresh", checks_until_complete=2)

    assert code == PAUSED, output
    assert "Workflow paused - batch job(s) submitted" in output
    assert not _records(project)


def test_at_the_wait_timeout_it_exits_4_and_a_later_run_collects_the_batch(project):
    code, output = _run(
        project, "--fresh", "--wait", "--wait-timeout", "0", checks_until_complete=2
    )

    assert code == PAUSED, output
    assert "still open for: summarize" in output, output
    assert f"agac run -a {WORKFLOW}" in output, output

    code, output = _run(project, *WAIT, checks_until_complete=2)

    assert code == 0, output
    assert _records(project)

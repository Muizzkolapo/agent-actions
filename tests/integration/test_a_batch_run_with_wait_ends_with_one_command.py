"""`agac run --wait` takes a batch workflow from submission to its end in one command.

A run that submits a batch pauses and exits 4; a wrapper had to match the paused
sentence and call `agac run` again in a loop. Every run here is one `agac run --sandbox`
through the CLI against the provider mock, whose batch needs the number of status checks
the sandbox scenario sets.
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


def _run(project, *args, checks_until_complete: int, held_seconds: float = 0):
    # The scenario holds the batch for the status checks before the one that completes it.
    (project / "sandbox.yml").write_text(
        f"batch: {{polls_until_complete: {checks_until_complete - 1}, "
        f"complete_after_seconds: {held_seconds}}}\n"
    )
    result = run_agac(project, "run", "-a", WORKFLOW, "--sandbox", "-u", "tools", *args)
    return result.returncode, result.stdout + result.stderr


# Every waiting run is bounded, so a batch that never completes fails a test, not the suite.
WAIT = ("--wait", "--poll", "1", "--wait-timeout", "120")


def test_a_batch_run_with_wait_ends_with_exit_0_after_the_batches_finish(project):
    code, output = _run(project, "--fresh", *WAIT, checks_until_complete=2)

    assert code == 0, output
    assert output.count("Workflow paused - batch job(s) submitted") == 2, output
    assert _records(project), "the batch was submitted but nothing was collected"


NO_WAIT = "Checking the batch job(s) again..."
ONE_SECOND = "Waiting 1s before checking the batch job(s) again..."


def test_without_a_poll_a_sandbox_run_checks_the_batch_again_with_no_wait(project):
    code, output = _run(
        project, "--fresh", "--wait", "--wait-timeout", "120", checks_until_complete=2
    )

    assert code == 0, output
    assert output.count("Workflow paused - batch job(s) submitted") == 2, output
    assert output.count(NO_WAIT) == 2, output
    assert "Waiting" not in output, output
    assert _records(project)


def test_a_batch_the_scenario_holds_by_time_is_checked_once_a_second(project):
    code, output = _run(
        project,
        "--fresh",
        "--wait",
        "--wait-timeout",
        "120",
        checks_until_complete=1,
        held_seconds=2,
    )

    assert code == 0, output
    assert NO_WAIT not in output, output
    # Two waits of a second reach the 2 s; passes with no wait between them would be many.
    assert 1 <= output.count(ONE_SECOND) <= 2, output
    assert _records(project)


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
    assert f"agac run -w {WORKFLOW} --sandbox --wait" in output, output

    code, output = _run(project, *WAIT, checks_until_complete=2)

    assert code == 0, output
    assert _records(project)


def test_a_plain_run_at_the_wait_timeout_names_the_plain_command_to_resume(project):
    """Without --sandbox the hint names no sandbox flag; a timeout of 0 stops after the submit."""
    result = run_agac(
        project, "run", "-a", WORKFLOW, "-u", "tools", "--fresh", "--wait", "--wait-timeout", "0"
    )
    output = result.stdout + result.stderr

    assert result.returncode == PAUSED, output
    assert "still open for: summarize" in output, output
    assert f"to check them and continue: agac run -w {WORKFLOW} --wait" in output, output

    result = run_agac(project, "run", "-a", WORKFLOW, "-u", "tools")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _records(project)

"""The sandbox template passes `agac sandbox check`: the end-to-end smoke test of the framework.

`agac init <name> --template sandbox` makes one workflow that uses each feature once: a tool
action, a guard, expect rules with repair and an llm_judge rule, versions and their merge, a
loop, a router and a join, a HITL action and a batch action. `agac sandbox check` runs it
offline with no key and compares the result with the project's `sandbox_expected.yml`. A
value that does not hold names the row and exits 1; a file the check cannot read exits 2
before any run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests._support.agac_cli import run_agac

WORKFLOW = "support_desk"
ENV = {"OPENAI_API_KEY": ""}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    created = run_agac(tmp_path, "init", "starter", "--template", "sandbox", env=ENV)
    assert created.returncode == 0, created.stdout + created.stderr
    return tmp_path / "starter"


def _check(project: Path, *args: str):
    return run_agac(project, "sandbox", "check", "-w", WORKFLOW, *args, env=ENV)


def _edit_expected(project: Path, change) -> None:
    path = project / "sandbox_expected.yml"
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_the_template_passes_its_check_offline_with_no_key(project):
    result = _check(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: all" in result.stdout, result.stdout
    assert "SANDBOX scenario sandbox.yml: 8 errors, 4 rules broken" in result.stdout
    # The check writes the sandbox output only: no real store, no real status file.
    io_dir = project / "agent_workflow" / WORKFLOW / "agent_io"
    assert (io_dir / "store" / f"{WORKFLOW}.sandbox.db").exists()
    assert not (io_dir / "store" / f"{WORKFLOW}.db").exists()
    assert not (io_dir / ".agent_status.json").exists()


def test_a_real_run_with_no_key_stops_at_preflight(project):
    result = run_agac(project, "run", "-w", WORKFLOW, env=ENV)

    assert result.returncode == 1, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "API key environment variable 'OPENAI_API_KEY' is not set" in output
    assert "Step 1/" not in output


def test_a_value_that_does_not_hold_is_named_and_exits_1(project):
    def wrong(data):
        data["actions"]["classify"]["filtered"] = 2
        data["scenario"]["errors"] = 9

    _edit_expected(project, wrong)

    result = _check(project)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL: 2 of" in result.stdout, result.stdout
    assert "  classify filtered: expected 2, got 1" in result.stdout
    assert "  scenario errors: expected 9, got 8" in result.stdout


def test_a_missing_expectations_file_exits_2_before_any_run(project):
    (project / "sandbox_expected.yml").unlink()

    result = _check(project)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "sandbox_expected.yml: no such file" in result.stderr
    assert "Starting agent run" not in result.stdout


def test_an_unknown_key_exits_2_before_any_run(project):
    _edit_expected(project, lambda data: data["actions"]["classify"].update(filterd=1))

    result = _check(project)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "actions.classify: unknown key 'filterd'" in result.stderr
    assert "Starting agent run" not in result.stdout


def _expect_only_action_values(project: Path) -> None:
    (project / "f.yml").write_text(
        "actions:\n  classify: {status: completed, success: 4, filtered: 1}\n"
    )


def _assert_no_result_fails(result) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert "  ✗ run" in result.stdout, result.stdout
    assert "wrote no result" in result.stdout
    assert "FAIL:" in result.stdout
    assert "PASS" not in result.stdout
    # The rows of the previous run's output are not read, so none of them is shown.
    assert "classify" not in result.stdout


def test_a_run_that_stops_before_it_writes_fails_and_shows_no_earlier_output(project):
    _expect_only_action_values(project)
    assert _check(project, "--expected", "f.yml").returncode == 0

    result = _check(project, "--expected", "f.yml", "--scenario", "nope.yml")

    assert "no scenario file nope.yml" in result.stderr
    _assert_no_result_fails(result)


def test_a_workflow_that_does_not_load_fails_the_check(project):
    _expect_only_action_values(project)
    assert _check(project, "--expected", "f.yml").returncode == 0
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().replace("$support_desk.Classify", "$support_desk.Nope"))

    _assert_no_result_fails(_check(project, "--expected", "f.yml"))


def test_a_run_lock_held_by_another_command_fails_the_check(project):
    from agent_actions.storage.run_lock import hold_run_lock

    _expect_only_action_values(project)
    assert _check(project, "--expected", "f.yml").returncode == 0

    with hold_run_lock(project / "agent_workflow" / WORKFLOW / "agent_io", WORKFLOW):
        result = _check(project, "--expected", "f.yml")

    assert "is in progress" in result.stderr
    _assert_no_result_fails(result)


def test_the_exit_code_of_a_run_that_wrote_no_result_is_compared_and_the_check_fails(project):
    (project / "f.yml").write_text("exit_code: 1\n")

    result = _check(project, "--expected", "f.yml", "--scenario", "nope.yml")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "  ✓ exit code  1" in result.stdout, result.stdout
    assert "  ✗ run" in result.stdout
    assert "FAIL: 1 of 2" in result.stdout


def test_an_action_entry_that_states_no_value_exits_2_before_any_run(project):
    (project / "f.yml").write_text("exit_code: 0\nactions:\n  classify:\n")

    result = _check(project, "--expected", "f.yml")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "f.yml: actions.classify: states no value" in result.stderr
    assert "Starting agent run" not in result.stdout


def test_the_check_run_twice_passes_twice_because_each_run_starts_fresh(project):
    first = _check(project)
    second = _check(project)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    # The second run cleared the first run's output and made each call again.
    assert "--fresh: cleared stored results" in second.stdout + second.stderr
    assert "SANDBOX scenario sandbox.yml: 8 errors, 4 rules broken" in second.stdout


FAILS_ONE_TICKET = """\
seed: 7
records:
  - match: {read_ticket.ticket_id: T-1001}
    actions:
      classify: {error: server_error}   # each attempt: the record fails for good
"""


def test_the_exit_code_of_a_run_that_fails_a_record_is_compared_as_a_value(project):
    (project / "fails_one.yml").write_text(FAILS_ONE_TICKET)
    (project / "f.yml").write_text("exit_code: 3\n")

    holds = _check(project, "--expected", "f.yml", "--scenario", "fails_one.yml")

    assert holds.returncode == 0, holds.stdout + holds.stderr
    assert "  ✓ exit code  3" in holds.stdout

    (project / "f.yml").write_text("exit_code: 0\n")

    differs = _check(project, "--expected", "f.yml", "--scenario", "fails_one.yml")

    assert differs.returncode == 1, differs.stdout + differs.stderr
    assert "  exit code: expected 0, got 3" in differs.stdout

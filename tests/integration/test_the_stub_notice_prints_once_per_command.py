"""The `SANDBOX` line that names the stubbed tools prints once per command.

`agac run --sandbox --wait` loads the workflow again for each pass, and the line printed
at each load. It prints once, after the scenario passed every check: a scenario that the
output check refuses calls nothing, so no line says that the run stubs a tool.
"""

from __future__ import annotations

from tests._support.agac_cli import run_agac
from tests.integration.test_a_sandbox_scenario_stubs_a_tool_action import (
    ENV,
    STUB_SEARCH,
    WORKFLOW,
    _called,
    _ok,
    _project,
    _said,
)

NOTICE = "SANDBOX: the scenario stubs these tool actions, so their code does not run: search"
ANOTHER_PASS = "Checking the batch job(s) again..."


def test_a_run_with_wait_prints_the_notice_once_over_its_passes(tmp_path):
    root = _project(tmp_path, STUB_SEARCH + "batch: {polls_until_complete: 1}\n")
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    rank = "    prompt: $catalog.Rank\n"
    config.write_text(config.read_text().replace(rank, rank + "    run_mode: batch\n"))

    result = _ok(
        run_agac(
            root,
            "run",
            "-w",
            WORKFLOW,
            "--sandbox",
            "--fresh",
            "--wait",
            "--wait-timeout",
            "120",
            env=ENV,
        )
    )

    said = result.stdout + result.stderr
    assert said.count(ANOTHER_PASS) >= 2, said
    assert said.count(NOTICE) == 1, said
    assert _called(root) == {"lookup"}


def test_a_scenario_the_output_check_refuses_prints_no_notice(tmp_path):
    root = _project(tmp_path, "actions:\n  search: {stub: true, pin: {orgin: x}}\n")

    result = run_agac(root, "run", "-w", WORKFLOW, "--sandbox", env=ENV)

    said = _said(result)
    assert result.returncode != 0, said
    assert "actions.search.pin.orgin" in said, said
    assert "stubs these tool actions" not in said, said

"""`agac dispositions --quarantined` lists unprocessed records, as its help says (1537).

It filtered on failed and exhausted only, so a record a FILE tool folded into another
(`consumed_into_another_record`) or left out (`tool_missing_record`) printed "No
quarantined records found." though `agac dispositions` counted it unprocessed.

Every command is a real `agac run` or `agac dispositions`.
"""

from __future__ import annotations

from pathlib import Path

from tests._support.agac_cli import run_agac
from tests.integration import test_a_fan_in_beside_a_file_tool_that_drops_a_record as dropping
from tests.integration import test_a_fan_in_beside_a_file_tool_that_folds_a_record as folding
from tests.integration import test_a_retry_answers_what_a_split_writes_below_it as splitting


def _quarantined(root: Path, workflow: str) -> str:
    ran = run_agac(root, "run", "-a", workflow, "--fresh")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    shown = run_agac(root, "dispositions", "-a", workflow, "--quarantined", env={"COLUMNS": "200"})
    assert shown.returncode == 0, shown.stdout + shown.stderr
    return shown.stdout


def _cells(output: str) -> str:
    """The table's text, any cell rich wrapped joined up again."""
    return "".join(
        "".join(cell.strip() for cell in line.split("│")) for line in output.splitlines()
    )


def test_a_record_folded_into_another_is_listed(tmp_path):
    root = folding._project(tmp_path)

    output = _quarantined(root, folding.WORKFLOW)

    assert "No quarantined records found" not in output, output
    assert "unprocessed" in output, output
    assert "consumed_into_another_record" in _cells(output), output
    assert folding._source_of(root, "b") in _cells(output), output


def test_a_record_a_file_tool_left_out_is_listed(tmp_path):
    root = dropping._project(tmp_path, "drop_c")

    output = _quarantined(root, dropping.WORKFLOW)

    assert "No quarantined records found" not in output, output
    assert "tool_missing_record" in _cells(output), output


def test_a_workflow_with_nothing_quarantined_still_says_so(tmp_path):
    root = splitting._project(tmp_path, "tool")

    output = _quarantined(root, splitting.WORKFLOW)

    assert "No quarantined records found" in output, output

"""A failed record is reported once, and the action's own line names the fault.

Errors move between layers as formatted strings, so the strategy and the result
collector each log the same record failure, and the action-level message is
built from the file-level exception — which never saw the record's cause. The
result is two console lines per failing record and a failure line that describes
file processing rather than what the user's code raised.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "species_id_cards"
WORKFLOW = "species_id_cards"
TOOL = "flatten_marks"
CAUSE = "could not parse mark_text: unexpected token"


@pytest.fixture(scope="module")
def crashed(tmp_path_factory):
    """Run the example with one tool raising, and hand back stdout+stderr and events.json."""
    project = tmp_path_factory.mktemp("cascade") / WORKFLOW
    shutil.copytree(EXAMPLE, project)

    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(
        config.read_text().replace("model_vendor: openai", "model_vendor: agac-provider")
    )
    (project / ".env").write_text("OPENAI_API_KEY=sk-not-used\n")

    tool_file = project / "tools" / WORKFLOW / "pipeline_tools.py"
    source = tool_file.read_text()
    marker = f"def {TOOL}("
    body = source.index("\n", source.index(":", source.index(marker)))
    tool_file.write_text(
        source[: body + 1] + f"    raise RuntimeError(\"{CAUSE} '~'\")\n" + source[body + 1 :]
    )

    result = subprocess.run(
        [
            str(Path(sys.executable).parent / "agac"),
            "run",
            "-a",
            WORKFLOW,
            "-u",
            "tools",
            "--fresh",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        # Pinned wide: a wrapped line splits the phrases asserted below, which
        # would make every assertion here depend on the terminal size.
        env={**os.environ, "COLUMNS": "240"},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"the tool was supposed to fail the run:\n{output[-2000:]}"

    events_file = project / "agent_workflow" / WORKFLOW / "agent_io" / "logs" / "events.json"
    events = [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]
    return output, events


def _console_lines_for_the_failed_action(output: str) -> list[str]:
    """Every console line between the failing step's header and the next step."""
    lines = output.splitlines()
    start = next(i for i, ln in enumerate(lines) if re.search(rf"Step \d+/\d+ {TOOL}\b", ln))
    end = next(i for i, ln in enumerate(lines[start + 1 :], start + 1) if ln.startswith("Step "))
    return [ln for ln in lines[start + 1 : end] if ln.strip()]


class TestAFailedRecordIsReportedOnce:
    def test_the_users_own_error_reaches_the_terminal(self, crashed):
        output, _ = crashed
        assert CAUSE in output, "the tool's own message never reached the user"

    def test_each_failing_record_is_reported_once(self, crashed):
        """Two records failed; the strategy and the collector each logged both."""
        output, _ = crashed
        assert output.count(CAUSE) == 2, (
            f"2 failing records should give 2 reports, got {output.count(CAUSE)}:\n  "
            + "\n  ".join(ln for ln in output.splitlines() if CAUSE in ln)
        )

    def test_the_failing_action_block_stays_small(self, crashed):
        output, _ = crashed
        block = _console_lines_for_the_failed_action(output)
        assert len(block) <= 4, "one fault still reads as a cascade:\n  " + "\n  ".join(block)


class TestTheActionLineNamesTheFault:
    def test_the_failure_line_carries_the_cause(self, crashed):
        """It reported file-processing plumbing and never what the tool raised."""
        output, _ = crashed
        line = next((ln for ln in output.splitlines() if "✗ " + TOOL in ln), None)
        assert line, "no failure line for the action"
        assert CAUSE in line, f"the action's own line does not name the fault:\n  {line}"

    def test_the_cause_leads_the_message(self, crashed):
        """`agac dispositions` truncates the reason at 60 chars, so a trailing cause is invisible."""
        output, _ = crashed
        line = next(ln for ln in output.splitlines() if "✗ " + TOOL in ln)
        detail = line.split("✗ ", 1)[1]
        assert detail.index(CAUSE) < detail.index("produced 0 successful"), (
            f"the cause must precede the record tally:\n  {line}"
        )


class TestTheLogFileKeepsEverything:
    @pytest.mark.parametrize(
        "layer",
        [
            "Error processing item",
            "Processing failed",
            "Failed to process backend entry",
            "incomplete for",
        ],
    )
    def test_every_layer_is_still_recorded(self, crashed, layer):
        _, events = crashed
        assert any(layer in e["message"] for e in events), (
            f"{layer!r} was dropped from events.json, not merely from the console"
        )


@pytest.fixture(scope="module")
def unreadable(tmp_path_factory):
    """Run with staged input that cannot be parsed, so a FILE fails rather than a record."""
    project = tmp_path_factory.mktemp("badfile") / WORKFLOW
    shutil.copytree(EXAMPLE, project)

    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(
        config.read_text().replace("model_vendor: openai", "model_vendor: agac-provider")
    )
    (project / ".env").write_text("OPENAI_API_KEY=sk-not-used\n")
    for staged in (project / "agent_workflow" / WORKFLOW / "agent_io" / "staging").glob("*.json"):
        staged.write_text("{ not valid json ][")

    result = subprocess.run(
        [
            str(Path(sys.executable).parent / "agac"),
            "run",
            "-a",
            WORKFLOW,
            "-u",
            "tools",
            "--fresh",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "COLUMNS": "240"},
    )
    return result.stdout + result.stderr


class TestAFileLevelFaultIsNotHidden:
    """An action can succeed with one file rejected; then this is the only notice."""

    def test_the_cause_still_reaches_the_terminal(self, unreadable):
        assert "Failed to parse json" in unreadable

    def test_the_rejected_file_is_named(self, unreadable):
        assert "Failed to process file entries.json" in unreadable

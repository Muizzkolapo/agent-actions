"""A FILE tool or HITL action below a failed record quarantines it, batch as online (1363).

Under batch, the row stored for a record the provider failed had no `content`, where online's
failed row keeps the record's content and nulls the failed action's namespace. A FILE tool's or
HITL action's `context_scope` pass runs before the cascade filter and does not look at the
record's state: it found no namespace for the failed action in batch's row and dropped the
record as `observe_field_missing`, which points the author at their own `context_scope`. The
action below stored nothing for the record. Online, and a Record tool under batch, store it
`cascade_skipped` with an `unprocessed upstream_unprocessed` disposition at every action below.

The workflow, the fault stand-in and the helpers are those of the guard test beside this one:
`summarize` fails page alpha, with an error row in a batch and a raise online, and the
actions below it run on the other three records. There is no guard here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.integration import test_a_guard_never_judges_a_record_its_upstream_failed as upstream
from tests.integration.test_a_guard_never_judges_a_record_its_upstream_failed import (
    FILE_TOOL_PUBLISH,
    LLM_PUBLISH,
    WORKFLOW,
)

MODES = ["online", "batch"]
BELOW = ("publish", "archive")
UNPROCESSED = ("unprocessed", "upstream_unprocessed")

HITL_PUBLISH = """\
    kind: hitl
    hitl: { port: 3999, instructions: "Review the summaries", timeout: 5 }
    context_scope: { observe: [summarize.summary, source.page_content] }
"""
_LLM_ARCHIVE = (
    f"    prompt: ${WORKFLOW}.Archive\n"
    "    context_scope: { observe: [publish.summary, source.page_content] }\n"
)
_HITL_ARCHIVE = (
    f"    prompt: ${WORKFLOW}.Archive\n"
    "    context_scope: { observe: [publish.hitl_status, source.page_content] }\n"
)
_FILE_TOOL_ARCHIVE = """\
    kind: tool
    granularity: File
    run_mode: online
    impl: roll_up_pages
    context_scope: { observe: [publish.summary, summarize.summary, source.page_content] }
"""


def _failed_alpha(tmp_path: Path, run_mode: str, publish: str, archive: str = _LLM_ARCHIVE):
    project = upstream.Project(tmp_path, run_mode, publish, "skip")
    config = project.root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    text = re.sub(r"    guard: \{[^\n]*\}\n", "", config.read_text())
    assert _LLM_ARCHIVE in text
    config.write_text(text.replace(_LLM_ARCHIVE, archive))
    project.alpha_fails()
    project.run_to_the_end("--fresh")
    return project


def _is_quarantined_at_every_action_below(project) -> None:
    alpha = project.alpha()
    for action in BELOW:
        assert project.dispositions(action).get(alpha) == UNPROCESSED, (
            action,
            project.dispositions(action),
        )
        assert project.states(action).get(alpha) == "cascade_skipped", action


@pytest.mark.parametrize("run_mode", MODES)
def test_a_file_tool_below_the_failure_quarantines_the_record(tmp_path, run_mode):
    project = _failed_alpha(tmp_path, run_mode, FILE_TOOL_PUBLISH)

    _is_quarantined_at_every_action_below(project)
    assert project.statuses() == {
        "summarize": "completed_with_failures",
        "publish": "completed",
        "archive": "completed",
    }


@pytest.mark.parametrize("run_mode", MODES)
def test_the_record_is_not_reported_as_a_missing_observe_field(tmp_path, run_mode):
    project = _failed_alpha(tmp_path, run_mode, FILE_TOOL_PUBLISH)

    reasons = {reason for _, reason in project.dispositions("publish").values()}
    assert "observe_field_missing" not in reasons


@pytest.mark.parametrize("run_mode", MODES)
def test_a_hitl_action_below_the_failure_quarantines_the_record(tmp_path, monkeypatch, run_mode):
    monkeypatch.setenv("AGAC_HITL_AUTO_APPROVE", "true")
    project = _failed_alpha(tmp_path, run_mode, HITL_PUBLISH, _HITL_ARCHIVE)

    _is_quarantined_at_every_action_below(project)


@pytest.mark.parametrize("run_mode", MODES)
def test_a_file_tool_two_levels_down_quarantines_it_too(tmp_path, run_mode):
    """`publish` is an LLM action, so batch stores alpha's tombstone there; the FILE tool
    below it reads both `publish` and `summarize`."""
    project = _failed_alpha(tmp_path, run_mode, LLM_PUBLISH, _FILE_TOOL_ARCHIVE)

    _is_quarantined_at_every_action_below(project)


@pytest.mark.parametrize("run_mode", MODES)
def test_the_retry_answers_it_at_every_action_once_the_fault_is_gone(tmp_path, run_mode):
    project = _failed_alpha(tmp_path, run_mode, FILE_TOOL_PUBLISH)
    alpha = project.alpha()
    project.alpha_fails(on=False)

    project.retry_to_the_end()

    for action in ("summarize", *BELOW):
        assert project.dispositions(action)[alpha] == ("success", None), action
    assert set(project.statuses().values()) == {"completed"}

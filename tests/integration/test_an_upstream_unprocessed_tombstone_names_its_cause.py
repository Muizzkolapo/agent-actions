"""A record quarantined below a failure says which action blocked it and why (1429).

The tombstone an action writes for a record an action above failed carried only
``{"reason": "upstream_unprocessed", "agent_type": "tombstone"}``. Which action had
blocked the record, and for what reason, was not on it, so a reader of the stored row
could not tell. Every action below the failure now copies the blocking action's name,
the state it left the record in and its reason onto the tombstone's metadata.

The workflow and fault stand-in are those of the guard test beside this one, without
the guard: ``summarize`` fails page alpha, ``publish`` and ``archive`` sit below it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.integration import test_a_guard_never_judges_a_record_its_upstream_failed as upstream
from tests.integration.test_a_guard_never_judges_a_record_its_upstream_failed import (
    FILE_TOOL_PUBLISH,
    LLM_PUBLISH,
    RECORD_TOOL_PUBLISH,
    WORKFLOW,
)

MODES = ["online", "batch"]
BELOW = ("publish", "archive")


def _failed_alpha(tmp_path: Path, run_mode: str, publish: str):
    project = upstream.Project(tmp_path, run_mode, publish, "skip")
    config = project.root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(re.sub(r"    guard: \{[^\n]*\}\n", "", config.read_text()))
    project.alpha_fails()
    project.run_to_the_end("--fresh")
    return project


@pytest.mark.parametrize("publish", [LLM_PUBLISH, RECORD_TOOL_PUBLISH, FILE_TOOL_PUBLISH])
@pytest.mark.parametrize("run_mode", MODES)
def test_each_tombstone_below_the_failure_names_the_action_and_its_reason(
    tmp_path, run_mode, publish
):
    project = _failed_alpha(tmp_path, run_mode, publish)
    alpha = project.alpha()
    failed_reason = project.dispositions("summarize")[alpha][1]
    assert failed_reason

    for action in BELOW:
        metadata = project.rows(action)[alpha]["metadata"]
        assert metadata["reason"] == "upstream_unprocessed", (action, metadata)
        assert metadata["upstream_action"] == "summarize", (action, metadata)
        assert metadata["upstream_state"] == "failed", (action, metadata)
        assert metadata["upstream_reason"] == failed_reason, (action, metadata)


@pytest.mark.parametrize("run_mode", MODES)
def test_records_that_were_answered_carry_no_upstream_cause(tmp_path, run_mode):
    project = _failed_alpha(tmp_path, run_mode, LLM_PUBLISH)
    alpha = project.alpha()

    for action in BELOW:
        for guid, row in project.rows(action).items():
            if guid != alpha:
                assert "upstream_action" not in (row.get("metadata") or {}), (action, row)


@pytest.mark.parametrize("run_mode", MODES)
def test_the_cause_is_gone_once_a_retry_answers_the_record(tmp_path, run_mode):
    project = _failed_alpha(tmp_path, run_mode, LLM_PUBLISH)
    alpha = project.alpha()
    project.alpha_fails(on=False)

    project.retry_to_the_end()

    for action in BELOW:
        assert project.dispositions(action)[alpha] == ("success", None), action
        metadata = project.rows(action)[alpha].get("metadata") or {}
        assert not set(metadata) & {"upstream_action", "upstream_state", "upstream_reason"}, (
            action,
            metadata,
        )

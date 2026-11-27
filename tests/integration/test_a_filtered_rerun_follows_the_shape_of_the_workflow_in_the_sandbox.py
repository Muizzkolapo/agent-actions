"""A filtered rerun runs the action it names and what reads it, whatever the action is.

The sandbox template uses each feature once: a guard, versions and their merge, a
loop with a retrieve entry, a router with two branches and a join, a HITL action and a
batch action. The
two high-priority tickets are answered again from each kind of action, offline, and
only the actions that read the named one run, on those tickets alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "support_desk"
ENV = {"OPENAI_API_KEY": ""}
HIGH_PRIORITY = 'source.priority == "high"'
RAN = re.compile(r"✓ (\w+)\s+(\d+) records?")

LOOP = {
    "reply_round_iter1__draft_reply": 2,
    "reply_round_iter1__check_reply": 2,
    # The retrieve step of the second round takes the round's guard, so it reads round 1.
    "reply_round_iter2__draft_reply__help": 2,
    "reply_round_iter2__draft_reply": 2,
    "reply_round_iter2__check_reply": 2,
}
AFTER_THE_LOOP = {"reply_round": 2, "approve_reply": 2, "tag_reply": 2}
TEAMS = {"billing_team": 1, "support_team": 1, "assigned": 2}
BELOW_THE_MERGE = {"merge_scores": 2, **LOOP, **TEAMS, **AFTER_THE_LOOP}


@pytest.fixture(scope="module")
def finished(tmp_path_factory) -> Path:
    """The template, run once in the sandbox to its end."""
    root = tmp_path_factory.mktemp("sandbox_rerun")
    created = run_agac(root, "init", "starter", "--template", "sandbox", env=ENV)
    assert created.returncode == 0, created.stdout + created.stderr
    project = root / "starter"
    first = run_agac(project, "run", "-w", WORKFLOW, "--sandbox", "--wait", env=ENV)
    assert first.returncode == 0, first.stdout + first.stderr
    return project


@pytest.fixture
def project(finished: Path, tmp_path: Path) -> Path:
    import shutil

    copy = tmp_path / "starter"
    shutil.copytree(finished, copy)
    return copy


def _rerun(project: Path, action: str, *flags: str):
    return run_agac(
        project,
        "run",
        "-w",
        WORKFLOW,
        "--sandbox",
        "--rerun",
        action,
        "--where",
        HIGH_PRIORITY,
        *flags,
        env=ENV,
    )


@pytest.mark.parametrize(
    ("action", "ran"),
    [
        ("classify", {"classify": 2, "score_1": 2, "score_2": 2, **BELOW_THE_MERGE}),
        # A versioned action is named as the config writes it, and each version runs.
        ("score", {"score_1": 2, "score_2": 2, **BELOW_THE_MERGE}),
        ("score_1", {"score_1": 2, **BELOW_THE_MERGE}),
        # The loop's result: the rounds above it and the router beside it do not run.
        ("reply_round", AFTER_THE_LOOP),
        ("reply_round_iter1__draft_reply", {**LOOP, **AFTER_THE_LOOP}),
        # A router: its two branches, the join, and what reads the join.
        ("by_queue", {"by_queue": 2, **TEAMS, "approve_reply": 2, "tag_reply": 2}),
        # One branch holds one of the two tickets.
        (
            "billing_team",
            {"billing_team": 1, "assigned": 1, "approve_reply": 1, "tag_reply": 1},
        ),
        ("approve_reply", {"approve_reply": 2, "tag_reply": 2}),
        ("tag_reply", {"tag_reply": 2}),
    ],
)
def test_only_the_named_action_and_what_reads_it_run_on_the_matching_tickets(project, action, ran):
    result = _rerun(project, action, "--wait")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-3000:]
    assert {name: int(count) for name, count in RAN.findall(output)} == ran, output[-3000:]


def test_a_batch_action_pauses_the_rerun_and_a_plain_run_collects_it(project):
    paused = _rerun(project, "tag_reply")

    assert paused.returncode == 4, paused.stdout + paused.stderr
    said = " ".join((paused.stdout + paused.stderr).split())
    assert "Rerun paused - batch job(s) submitted for: tag_reply" in said

    collected = run_agac(project, "run", "-w", WORKFLOW, "--sandbox", "--wait", env=ENV)

    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert dict(RAN.findall(collected.stdout + collected.stderr)) == {"tag_reply": "2"}


def test_the_rerun_reads_and_writes_the_sandbox_output_only(project):
    result = _rerun(project, "classify", "--wait")

    assert result.returncode == 0, result.stdout + result.stderr
    io_dir = project / "agent_workflow" / WORKFLOW / "agent_io"
    assert not (io_dir / "store" / f"{WORKFLOW}.db").exists()
    assert not (io_dir / ".agent_status.json").exists()


def test_a_dry_run_counts_the_tickets_and_runs_nothing(project):
    result = _rerun(project, "classify", "--dry-run")

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output
    assert "2 of 4 record(s) of 'classify' match; the other 2 keep their answers" in output
    assert not RAN.findall(output)

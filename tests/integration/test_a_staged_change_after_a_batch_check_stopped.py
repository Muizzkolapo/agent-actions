"""A staged change made after a batch check stopped is answered at every action (#1921).

A check that stops with its batch still out (an interrupt, a crash, an ordinary provider
error) leaves the action to be reset to pending by the next run. Pending, it was not
seen as waiting on a batch, so a change made then was never marked: the batch was
collected as it was sent, and a record changed or added in its file was lost.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests._support.agac_cli import REPO
from tests.integration.test_a_staged_input_change_and_fresh_while_a_batch_is_open import (
    _SENT,
    WORKFLOW,
    _actions,
    _collect,
    _held,
    _project,
    _run,
    _stage,
)

# `agac run`, whose check on the batch stops the way *how* names.
_AGAC_WHOSE_CHECK_STOPS = """
import os, sys
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

how = os.environ["CHECK_STOPS"]

def stopped(self, batch_id):
    if how == "interrupt":
        raise KeyboardInterrupt()
    if how == "crash":
        os._exit(1)
    raise RuntimeError("the provider could not be asked")

AgacBatchClient._fetch_status = stopped
from agent_actions.cli.main import main
sys.argv[0] = "agac"
sys.exit(main())
"""


def _stop_the_check(root, how: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            _AGAC_WHOSE_CHECK_STOPS,
            "run",
            "-a",
            WORKFLOW,
            "-u",
            "tools",
            "--sandbox",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(REPO), "CHECK_STOPS": how},
    )


@pytest.mark.parametrize("how", ["interrupt", "crash", "provider_error"])
@pytest.mark.parametrize("shape", ["tag_after_a_tool", "tag_first"])
def test_a_change_after_the_check_stopped_is_answered(tmp_path, shape, how):
    root = _project(tmp_path, shape)
    code, output = _run(root)
    assert code == 4, output
    _SENT.pop(root)
    _stop_the_check(root, how)
    _stage(root, "b.json", [{"id": "b1", "n": 9}, {"id": "b2", "n": 5}])

    codes = _collect(root)

    assert codes[-1] == 0
    assert _SENT[root] == [2], "the open batch is collected, and only b.json is sent"
    assert _held(root, "n") == {action: [1, 2, 5, 9] for action in _actions(root)}

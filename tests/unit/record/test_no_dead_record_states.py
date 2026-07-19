"""Regression tests for removed ``RecordState`` members.

``committed`` and ``guard_deferred`` were listed in the enum, the resettable
set, and the disposition map but had **zero stamp sites** — no code path ever
wrote them. They are removed. These tests pin the removal: the enum rejects the
values, the derived state sets exclude them, the disposition map has no entry,
``derive_disposition`` fails loudly on a record carrying them, and no source code
references the qualified members.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_actions.record.disposition import _STATE_TO_DISPOSITION, derive_disposition
from agent_actions.record.envelope import RecordEnvelopeError
from agent_actions.record.state import RESETTABLE_DOWNSTREAM_STATES, RecordState

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REMOVED_VALUES = ["committed", "guard_deferred"]
_REMOVED_NAMES = ["COMMITTED", "GUARD_DEFERRED"]


@pytest.mark.parametrize("value", _REMOVED_VALUES)
def test_value_not_constructible(value):
    with pytest.raises(ValueError):
        RecordState(value)


@pytest.mark.parametrize("name", _REMOVED_NAMES)
def test_member_absent_from_enum(name):
    assert name not in RecordState.__members__


@pytest.mark.parametrize("value", _REMOVED_VALUES)
def test_absent_from_resettable_states(value):
    assert value not in {s.value for s in RESETTABLE_DOWNSTREAM_STATES}


@pytest.mark.parametrize("value", _REMOVED_VALUES)
def test_absent_from_disposition_map(value):
    assert value not in {s.value for s in _STATE_TO_DISPOSITION}


@pytest.mark.parametrize("value", _REMOVED_VALUES)
def test_derive_disposition_rejects_removed_state(value):
    with pytest.raises(RecordEnvelopeError, match="unknown _state value"):
        derive_disposition({"_state": value})


def test_no_qualified_references_in_source():
    """No agent_actions/ code references RecordState.COMMITTED / .GUARD_DEFERRED."""
    result = subprocess.run(
        [
            "grep",
            "-rnE",
            r"RecordState\.(COMMITTED|GUARD_DEFERRED)",
            str(_REPO_ROOT / "agent_actions"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.stdout == "", f"stray references:\n{result.stdout}"

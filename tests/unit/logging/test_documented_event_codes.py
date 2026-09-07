"""The event reference must name events that exist, with the codes they emit."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import agent_actions.logging.events as events

_REFERENCE = (
    Path(__file__).resolve().parents[3]
    / "docs.agent-actions"
    / "docs"
    / "reference"
    / "execution"
    / "artifacts.md"
)

# Matches "`ActionStartEvent` (A001)" and "**R001 `RetryExhaustedEvent`**".
_SUFFIXED = re.compile(r"`(\w+Event)`\s*\(([A-Z]+\d+)\)")
_PREFIXED = re.compile(r"\*\*([A-Z]+\d+)\s+`(\w+Event)`\*\*")
_ANY_NAME = re.compile(r"`(\w+Event)`")


def _documented_names() -> list[str]:
    return sorted(set(_ANY_NAME.findall(_REFERENCE.read_text())))


def _documented_pairs() -> list[tuple[str, str]]:
    text = _REFERENCE.read_text()
    pairs = [(name, code) for name, code in _SUFFIXED.findall(text)]
    pairs += [(name, code) for code, name in _PREFIXED.findall(text)]
    return sorted(set(pairs))


def _actual_codes() -> dict[str, str]:
    codes = {}
    for name in dir(events):
        if not name.endswith("Event"):
            continue
        cls = getattr(events, name)
        if not inspect.isclass(cls):
            continue
        try:
            codes[name] = cls().to_dict()["code"]
        except Exception:  # noqa: BLE001 - a class needing args has no documentable code
            continue
    return codes


def test_the_regexes_still_find_the_catalogue():
    """Guards the parser: a regex that matches nothing would pass every other test."""
    assert len(_documented_names()) > 40, (
        f"only {len(_documented_names())} event names parsed — the name regex drifted"
    )
    assert len(_documented_pairs()) > 40, (
        f"only {len(_documented_pairs())} event/code pairs parsed — the code regex drifted"
    )


@pytest.mark.parametrize("name", _documented_names())
def test_a_documented_event_class_exists(name):
    assert hasattr(events, name), (
        f"{_REFERENCE.name} names {name}, which is not in agent_actions.logging.events"
    )


@pytest.mark.parametrize("name,code", _documented_pairs())
def test_a_documented_event_exists_and_emits_its_documented_code(name, code):
    actual = _actual_codes()
    assert name in actual, (
        f"{_REFERENCE.name} names {name}, which is not in agent_actions.logging.events"
    )
    assert actual[name] == code, f"{name} emits {actual[name]}, but the reference says {code}"

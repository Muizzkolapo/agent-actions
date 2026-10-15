"""The per-module event counts the logging docs give are the classes the modules define."""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest

from agent_actions.logging.core.events import BaseEvent

_LOGGING = Path(__file__).resolve().parents[3] / "agent_actions" / "logging"
_MODULES = [
    "workflow_events",
    "batch_events",
    "llm_events",
    "validation_events",
    "initialization_events",
    "io_events",
    "data_pipeline_events",
    "cache_events",
]
_ARCHITECTURE_ROW = re.compile(r"^\| `(\w+_events)\.py` \| [^|]* \| (\d+) \|$", re.M)
_MANIFEST_ROW = re.compile(r"^\| `(\w+_events)\.py` \|.*?\b(\d+) classes\.", re.M)


def _defined(module: str) -> int:
    mod = importlib.import_module(f"agent_actions.logging.events.{module}")
    return sum(
        1
        for _, cls in inspect.getmembers(mod, inspect.isclass)
        if issubclass(cls, BaseEvent) and cls is not BaseEvent and cls.__module__ == mod.__name__
    )


def _counts(page: Path, row: re.Pattern[str]) -> dict[str, int]:
    return {name: int(count) for name, count in row.findall(page.read_text(encoding="utf-8"))}


@pytest.mark.parametrize(
    "page, row",
    [
        (_LOGGING / "ARCHITECTURE.md", _ARCHITECTURE_ROW),
        (_LOGGING / "events" / "_MANIFEST.md", _MANIFEST_ROW),
    ],
    ids=["ARCHITECTURE", "events-MANIFEST"],
)
def test_each_module_count_is_what_the_module_defines(page, row):
    given = _counts(page, row)

    assert sorted(given) == sorted(_MODULES)
    assert given == {module: _defined(module) for module in _MODULES}


def test_the_total_the_architecture_page_gives_is_the_sum_of_its_modules():
    text = (_LOGGING / "ARCHITECTURE.md").read_text(encoding="utf-8")
    (total,) = set(re.findall(r"All (\d+) event types are re-exported", text))

    assert int(total) == sum(_defined(module) for module in _MODULES)

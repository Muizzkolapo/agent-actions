"""A `dependencies` a docs code block shows is a list, the only form the loader takes.

`dependencies: extract` is refused at load ("Input should be a valid list"), so a reader
who copies it gets no workflow at all. Code blocks only: prose may name the key without
showing a value.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig

_REPO = Path(__file__).resolve().parents[3]
_PAGES = sorted(
    [
        *(_REPO / "docs.agent-actions" / "docs").rglob("*.md*"),
        *(_REPO / "agent_actions" / "skills").rglob("*.md"),
    ]
)
_FENCE = re.compile(r"^\s*(```|~~~)")
_DEPENDENCIES = re.compile(r"^\s*(?:-\s+)?dependencies:(?P<value>[^#]*)")


def _scalars(page: Path) -> list[str]:
    found = []
    in_block = False
    for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
        if _FENCE.match(line):
            in_block = not in_block
            continue
        match = _DEPENDENCIES.match(line) if in_block else None
        if match and match["value"].strip() and not match["value"].strip().startswith("["):
            found.append(f"{page.relative_to(_REPO)}:{number}: {line.strip()}")
    return found


def test_the_loader_refuses_a_scalar():
    with pytest.raises(ValidationError, match="valid list"):
        ActionConfig(name="b", intent="read a", dependencies="a")


def test_the_docs_show_dependencies():
    assert sum("dependencies:" in page.read_text(encoding="utf-8") for page in _PAGES) > 20


def test_no_page_shows_a_scalar():
    assert [line for page in _PAGES for line in _scalars(page)] == []

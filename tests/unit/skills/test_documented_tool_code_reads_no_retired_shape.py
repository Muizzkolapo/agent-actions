"""Tool code the skill and the docs show reaches for no input shape a tool is not handed.

A record tool reads `data["action"]["field"]`, one level, a version merge included, and
a FILE tool reads flat observed keys. Two shapes the pages once showed raise `KeyError`
on every record: a version read under its own name twice, and a record's `content`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_PAGES = sorted(
    [
        *(_REPO / "docs.agent-actions" / "docs").rglob("*.md*"),
        *(_REPO / "agent_actions" / "skills").rglob("*.md"),
    ]
)
_PYTHON = re.compile(r"^```python\n(.*?)^```", re.S | re.M)
_TWICE = re.compile(r"""\[(f?["'][^"']+["'])\]\[\1\]""")
_CONTENT = re.compile(r"""\[["']content["']\]""")


def _lines(pattern: re.Pattern[str]) -> list[str]:
    found = []
    for page in _PAGES:
        for block in _PYTHON.findall(page.read_text(encoding="utf-8")):
            found += [
                f"{page.relative_to(_REPO)}: {line.strip()}"
                for line in block.splitlines()
                if pattern.search(line)
            ]
    return found


def test_the_pages_show_tool_code():
    assert sum(len(_PYTHON.findall(page.read_text(encoding="utf-8"))) for page in _PAGES) > 40


@pytest.mark.parametrize(
    ("pattern", "line"),
    [
        (_TWICE, 'v1 = data["evaluate_1"]["evaluate_1"]["verdict"]'),
        (_TWICE, 'votes = [data[f"verify_{i}"][f"verify_{i}"]["passed"] for i in [1, 2]]'),
        (_CONTENT, 'key = record["content"]["extract_facts"]["fact_text"]'),
        (_CONTENT, 'content = record["content"]'),
    ],
)
def test_a_retired_shape_is_recognised(pattern, line):
    assert pattern.search(line)


@pytest.mark.parametrize("line", ['v1 = data["evaluate_1"]["verdict"]', 'key = item["fact_text"]'])
def test_a_delivered_shape_is_not(line):
    assert not _TWICE.search(line) and not _CONTENT.search(line)


def test_no_tool_reads_a_version_under_its_name_twice():
    assert _lines(_TWICE) == []


def test_no_tool_reads_a_record_content():
    assert _lines(_CONTENT) == []

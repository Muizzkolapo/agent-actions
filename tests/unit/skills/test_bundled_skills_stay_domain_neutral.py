"""The bundled skills teach agent-actions, not one user's domain.

A skill is copied into every project that runs ``agac skills install``. Words from
one project's domain (an assessment generator, here) make a skill read as if
agent-actions served only that domain, and phrases such as "correct answer" assume
that every output is an answer with a key. Each skill names the domain-neutral
terms it uses in its own Terms table.
"""

import re
from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parents[3] / "agent_actions" / "skills"
_PAGES = sorted(p for p in _SKILLS.rglob("*") if p.is_file() and p.suffix in {".md", ".py"})

# Whole words (case-insensitive), and phrases matched as phrases.
_WORDS = ("quiz", "quizzes", "exam", "exams", "distractor", "distractors", "qanalabs")
_PHRASES = ("answer key", "correct answer", "correct option")
_PREFIXES = ("ql_",)

_PATTERN = re.compile(
    "|".join(
        [rf"\b{re.escape(w)}\b" for w in _WORDS]
        + [rf"\b{re.escape(p)}\b" for p in _PHRASES]
        + [rf"(?<![A-Za-z0-9]){re.escape(p)}" for p in _PREFIXES]
    ),
    re.IGNORECASE,
)


def test_there_are_skill_pages():
    assert _PAGES, f"no skill pages under {_SKILLS}"


@pytest.mark.parametrize("page", _PAGES, ids=lambda p: str(p.relative_to(_SKILLS)))
def test_page_uses_no_domain_words(page: Path):
    found = [
        f"{page.relative_to(_SKILLS)}:{number}: {match.group(0)!r}"
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), start=1)
        for match in _PATTERN.finditer(line)
    ]
    assert not found, "Domain words in a bundled skill:\n" + "\n".join(found)


def test_the_pattern_finds_what_it_should():
    assert _PATTERN.search("Write a Quiz question")
    assert _PATTERN.search("the correct answer is hidden")
    assert _PATTERN.search("see ql_compact")
    assert not _PATTERN.search("an example, an exact value, a sql_query")
    assert not _PATTERN.search("the answer of the model")

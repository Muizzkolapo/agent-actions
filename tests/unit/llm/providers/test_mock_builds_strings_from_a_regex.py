"""The mock builds a string a regular expression matches, for the subset it reads.

Each pattern in the table gets 50 seeded samples, and every sample must match the pattern
as Python's own `re` reads it. A pattern outside the subset is refused by name, so the
caller can fall back to generate-and-check.
"""

from __future__ import annotations

import random
import re

import pytest

from agent_actions.llm.providers.agac.regex_gen import UnsupportedPattern, generate

PATTERNS = [
    r"^[A-Z]{3}-\d{4}$",
    r"INV-\d+",
    r"(foo|bar)baz",
    r"[^aeiou]{2,4}",
    r"\w+@\w+\.com",
    r"^\d{3}(-\d{2})?$",
    r"^(?P<year>\d{4})-(?:0[1-9]|1[0-2])$",
    r"a{,2}b*c?",
    r"[\]a-c-]+x",
    r"\S+\s\S+",
    r"^\W\D$",
    r"x{2",
    r"colou?r|gr[ae]y",
    r"[\d.]{1,5}%",
    r"^[a-z]+?\.[A-Z]{2,}$",
    r"\(\d{3}\) \d{3}-\d{4}",
]


@pytest.mark.parametrize("pattern", PATTERNS)
def test_every_sample_matches_its_pattern(pattern):
    rng = random.Random(7)
    samples = [generate(pattern, rng) for _ in range(50)]

    assert [s for s in samples if not re.fullmatch(pattern, s)] == []


@pytest.mark.parametrize("pattern", [r"INV-\d+", r"[^aeiou]{2,4}", r"(foo|bar)baz"])
def test_samples_vary(pattern):
    rng = random.Random(3)

    assert len({generate(pattern, rng) for _ in range(50)}) > 1


def test_one_seed_gives_one_sample():
    assert generate(r"[A-Z]{8}", random.Random(11)) == generate(r"[A-Z]{8}", random.Random(11))


@pytest.mark.parametrize(
    "pattern",
    [r"(?=a)b", r"(?!a)b", r"(?<=a)b", r"\bword", r"(a)\1", r"(?i)abc", r"\p{L}", r"a**"],
)
def test_a_pattern_outside_the_subset_is_refused(pattern):
    with pytest.raises(UnsupportedPattern):
        generate(pattern, random.Random(0))

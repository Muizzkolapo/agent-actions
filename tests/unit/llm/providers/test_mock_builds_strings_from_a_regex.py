"""The mock builds a string a regular expression matches, for the subset it reads.

Each pattern in the table gets 50 seeded samples, and every sample must match the pattern
as Python's own `re` reads it. A pattern outside the subset is refused by name, so the
caller can fall back to generate-and-check.
"""

from __future__ import annotations

import logging
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
    r"[\n-\r]+",
    r"a{1000}",
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


@pytest.mark.parametrize("pattern", [r"[\d-z]", r"a{2}{3}", r"{3}", r"x+{2}"])
def test_a_pattern_python_refuses_is_refused(pattern):
    with pytest.raises(UnsupportedPattern):
        generate(pattern, random.Random(0))


@pytest.mark.parametrize("pattern", [r"a{1001}", r"a{2,5000}", r"a{1001,}", r"a{,99999}"])
def test_a_repeat_count_above_the_cap_is_refused(pattern):
    with pytest.raises(UnsupportedPattern):
        generate(pattern, random.Random(0))


NESTED = "(?:" * 400 + "a" + ")" * 400
TOO_DEEP_FOR_RE = "(?:" * 2000 + "a" + ")" * 2000


@pytest.mark.parametrize("pattern", [NESTED, TOO_DEEP_FOR_RE], ids=["nested", "deeper"])
def test_a_pattern_nested_too_deep_is_refused(pattern):
    with pytest.raises(UnsupportedPattern):
        generate(pattern, random.Random(0))


@pytest.mark.parametrize("pattern", [NESTED, TOO_DEEP_FOR_RE], ids=["nested", "deeper"])
def test_a_schema_pattern_nested_too_deep_falls_back_to_plain_text(pattern):
    from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator

    FakeDataGenerator.set_context(seed=1)

    assert FakeDataGenerator.from_pattern(pattern) is None
    assert isinstance(
        FakeDataGenerator.generate_from_schema({"type": "string", "pattern": pattern}, 1), str
    )


def _answer_with_rule_pattern(pattern: str) -> dict:
    from agent_actions.llm.providers.agac.client import AgacClient

    AgacClient.reset()
    config = {
        "name": "extract",
        "json_mode": True,
        "expect": {
            "repair": "none",
            "expectations": [
                {"type": "matches_regex", "field": "code", "params": {"pattern": pattern}}
            ],
        },
    }
    schema = {"type": "object", "properties": {"code": {"type": "string"}}}
    [record] = AgacClient.call_json(
        None, config, "Extract.", "{}", {"name": "o", "schema": schema}
    )
    return record


@pytest.mark.parametrize("pattern", [NESTED, TOO_DEEP_FOR_RE], ids=["nested", "deeper"])
def test_a_rule_pattern_nested_too_deep_still_gets_a_record(pattern):
    assert isinstance(_answer_with_rule_pattern(pattern)["code"], str)


def test_a_rule_pattern_python_cannot_compile_is_named_as_unmeetable(caplog):
    caplog.set_level(logging.WARNING)

    _answer_with_rule_pattern(TOO_DEEP_FOR_RE)

    assert any("Python cannot compile its pattern" in r.getMessage() for r in caplog.records)

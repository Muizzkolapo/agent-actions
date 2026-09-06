"""What the examples' reprompt validation UDFs accept and reject, pinned.

These UDFs are the behaviour an `expect:` suite has to reproduce when the
examples move off `reprompt:`. Pinning them here first means the migration is
measured against a recorded oracle rather than a reading of the code.

Loaded by path: the modules live under `examples/`, which is not an importable
package, and the decorator's registry is keyed by bare function name so two
examples defining `check_required_fields` would collide in it.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _load(example: str) -> Any:
    path = EXAMPLES / example / "tools" / "shared" / "reprompt_validations.py"
    spec = importlib.util.spec_from_file_location(f"_baseline_{example}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fn(example: str, name: str) -> Callable[[Any], bool]:
    return getattr(_load(example), name)


# Every example that declares check_required_fields. The four are separate
# files; if they ever diverge, this parametrisation is what says so.
REQUIRED_FIELDS_EXAMPLES = [
    "contract_reviewer",
    "incident_triage",
    "product_listing_enrichment",
    "review_analyzer",
]


@pytest.mark.parametrize("example", REQUIRED_FIELDS_EXAMPLES)
@pytest.mark.parametrize(
    "record,expected",
    [
        ({"title": "Outage", "severity": 3}, True),
        ({"title": "Outage", "severity": None}, False),
        ({"severity": None}, False),
        ({"title": "Outage", "_internal": None}, True),
        ({"_parse_error": "bad json"}, False),
        ({}, False),
        ([{"title": "Outage", "severity": 3}], True),
        ([{"title": "Outage", "severity": None}], False),
        ([], False),
        ("not a record", False),
    ],
)
def test_check_required_fields(example: str, record: Any, expected: bool) -> None:
    assert _fn(example, "check_required_fields")(record) is expected


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"primary_bisac_code": "FIC000000"}, True),
        ({"primary_bisac_code": "FIC00000"}, False),
        ({"primary_bisac_code": "FIC0000000"}, False),
        ({"primary_bisac_code": ""}, False),
        ({"primary_bisac_code": None}, False),
        ({"primary_bisac_code": 123456789}, False),
        ({}, False),
        ({"primary_bisac_code": "FIC000000", "_parse_error": "x"}, False),
        ([{"primary_bisac_code": "FIC000000"}], True),
        ([], False),
    ],
)
def test_check_valid_bisac(record: Any, expected: bool) -> None:
    assert _fn("book_catalog_enrichment", "check_valid_bisac")(record) is expected


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"marketing_description": " ".join(["word"] * 50)}, True),
        ({"marketing_description": " ".join(["word"] * 49)}, False),
        ({"marketing_description": " ".join(["word"] * 200)}, True),
        ({"marketing_description": ""}, False),
        ({}, False),
        ({"marketing_description": " ".join(["word"] * 50), "_parse_error": "x"}, False),
        ([{"marketing_description": " ".join(["word"] * 50)}], True),
        ([], False),
    ],
)
def test_check_description_word_count(record: Any, expected: bool) -> None:
    assert _fn("book_catalog_enrichment", "check_description_word_count")(record) is expected


def test_the_three_live_udfs_are_the_only_ones_any_config_references() -> None:
    """A UDF no config names cannot regress, and does not need migrating.

    `check_no_parse_error` and `check_genre_classification` are defined and
    referenced nowhere; this is what says so, so the migration does not carry
    them forward on the assumption that something uses them.
    """
    referenced: set[str] = set()
    for config in EXAMPLES.rglob("agent_config/*.yml"):
        for line in config.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("validation:"):
                value = stripped.split(":", 1)[1].strip().strip("\"'")
                referenced.add(value.split("#")[0].strip().strip("\"'"))

    assert referenced == {
        "check_required_fields",
        "check_valid_bisac",
        "check_description_word_count",
    }

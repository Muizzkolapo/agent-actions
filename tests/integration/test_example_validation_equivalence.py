"""Each replacement rule decides the way the UDF it replaces decided.

The examples' `reprompt: {validation: ...}` blocks become `expect:` rules. This
runs both over the same table and compares, so the migration is measured rather
than described. It is deleted with the UDFs once they are gone.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_actions.expectations import registry

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _udf(example: str, name: str) -> Callable[[Any], bool]:
    path = EXAMPLES / example / "tools" / "shared" / "reprompt_validations.py"
    spec = importlib.util.spec_from_file_location(f"_equiv_{example}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


def _rule(type_name: str, record: dict[str, Any], field: str | None, **params) -> bool:
    """Run one expectation the way the runner would, and return its verdict."""
    etype = registry.get(type_name)
    assert etype is not None, f"{type_name} is not registered"
    if registry.is_record_scoped(type_name):
        return bool(etype.check(record, params)[0])
    if field not in record:
        # A selector naming a field the record lacks is a failed outcome, which
        # is what the runner reports rather than raising.
        return False
    return bool(etype.check(record[field], params)[0])


def _unwrap(record: Any) -> Any:
    """The UDFs accept a length-1 list; the rules only ever see one record."""
    if isinstance(record, list):
        return record[0] if record else {}
    return record


# --- check_required_fields -> no_null_fields --------------------------------

REQUIRED_FIELDS_CASES = [
    {"title": "Outage", "severity": 3},
    {"title": "Outage", "severity": None},
    {"severity": None},
    {"title": "Outage", "_internal": None},
    {},
    {"a": None, "b": None},
    {"only": "value"},
]


@pytest.mark.parametrize(
    "example",
    ["contract_reviewer", "incident_triage", "product_listing_enrichment", "review_analyzer"],
)
@pytest.mark.parametrize("record", REQUIRED_FIELDS_CASES)
def test_no_null_fields_matches_check_required_fields(example: str, record: dict[str, Any]):
    udf = _udf(example, "check_required_fields")
    assert _rule("no_null_fields", record, None) is udf(record), record


# --- check_description_word_count -> word_count_between ---------------------

WORD_COUNT_CASES = [
    {"marketing_description": " ".join(["word"] * 50)},
    {"marketing_description": " ".join(["word"] * 49)},
    {"marketing_description": " ".join(["word"] * 200)},
    {"marketing_description": ""},
    {},
]


@pytest.mark.parametrize("record", WORD_COUNT_CASES)
def test_word_count_between_matches_the_word_count_udf(record: dict[str, Any]):
    udf = _udf("book_catalog_enrichment", "check_description_word_count")
    rule = _rule("word_count_between", record, "marketing_description", min=50)
    assert rule is udf(_unwrap(record)), record


# --- check_valid_bisac -> matches_regex -------------------------------------

BISAC_PATTERN = r"^[A-Z]{3}\d{6}$"

BISAC_AGREED_CASES = [
    {"primary_bisac_code": "FIC000000"},
    {"primary_bisac_code": "FIC00000"},
    {"primary_bisac_code": "FIC0000000"},
    {"primary_bisac_code": ""},
    {},
]


@pytest.mark.parametrize("record", BISAC_AGREED_CASES)
def test_matches_regex_agrees_with_the_bisac_udf(record: dict[str, Any]):
    udf = _udf("book_catalog_enrichment", "check_valid_bisac")
    rule = _rule("matches_regex", record, "primary_bisac_code", pattern=BISAC_PATTERN)
    assert rule is udf(_unwrap(record)), record


@pytest.mark.parametrize("code", ["ABCDEFGHI", "fic000000", "FIC00000X", "123456789"])
def test_the_bisac_rule_is_deliberately_stricter_than_the_udf(code: str):
    """A recorded tightening, not an accident.

    The UDF accepted any nine-character string. A BISAC code is three letters
    then six digits, so these nine-character strings were accepted before and
    are rejected now. Anything the UDF rejected stays rejected.
    """
    record = {"primary_bisac_code": code}
    udf_says = _udf("book_catalog_enrichment", "check_valid_bisac")(record)
    rule_says = _rule("matches_regex", record, "primary_bisac_code", pattern=BISAC_PATTERN)

    assert rule_says is False
    assert udf_says is True, f"{code} was expected to be a case the UDF let through"

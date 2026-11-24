"""The schema feedback a repair prompt carries lists its fields in one order in every process.

Python orders a set of strings by a hash that changes per process. Feedback built from a
set would give the same answer a different repair prompt in each run.
"""

from __future__ import annotations

import os
import subprocess
import sys

from agent_actions.validation.schema_output_validator import validate_output_against_schema

FIELDS = ["delta", "alpha", "kilo", "echo", "bravo", "juliet", "charlie", "india", "golf"]
SCHEMA = {
    "name": "wide",
    "type": "object",
    "properties": {name: {"type": "string"} for name in FIELDS},
    "required": FIELDS[:6],
}
OUTPUT = {"zulu": "z", "yankee": "y", "xray": "x", "whiskey": "w", "victor": "v"}

SNIPPET = f"""
from agent_actions.validation.schema_output_validator import validate_output_against_schema
report = validate_output_against_schema({OUTPUT!r}, {SCHEMA!r}, "a", strict_mode=True)
print(report.validation_errors, report.missing_optional)
"""


def test_the_feedback_names_each_field_list_in_sorted_order():
    report = validate_output_against_schema(OUTPUT, SCHEMA, "a", strict_mode=True)

    assert report.missing_required == sorted(FIELDS[:6])
    assert report.missing_optional == sorted(FIELDS[6:])
    assert report.extra_fields == sorted(OUTPUT)
    assert f"Missing required fields: {', '.join(sorted(FIELDS[:6]))}" in report.validation_errors
    assert (
        f"Extra fields not allowed in strict mode: {', '.join(sorted(OUTPUT))}"
        in report.validation_errors
    )


def test_two_processes_with_other_hash_seeds_give_the_same_feedback():
    printed = set()
    for seed in ("1", "2", "3"):
        result = subprocess.run(
            [sys.executable, "-c", SNIPPET],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        printed.add(result.stdout)

    assert len(printed) == 1, printed

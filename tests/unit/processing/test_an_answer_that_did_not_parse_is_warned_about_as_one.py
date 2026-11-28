"""An answer that did not parse is warned about as such, not as one with odd fields.

Its fields are the error's own (`raw_response`, `_parse_error`). Checked against the
schema, they read as unexpected output and the schema's fields as missing, which sent
a reader looking at the schema when the answer was simply not JSON.
"""

import logging

import pytest

from agent_actions.processing.helpers import SCHEMA_KEY, warn_on_schema_mismatch

SCHEMA = {
    "type": "object",
    "properties": {"tag": {"type": "string"}},
    "required": ["tag"],
}


@pytest.mark.parametrize(
    "answer",
    [
        {"raw_response": "The page is about tides.", "_parse_error": "not JSON"},
        [{"raw_response": "cut off {", "_parse_error": "unfinished"}],
    ],
)
def test_the_warning_says_the_answer_did_not_parse(answer, caplog):
    with caplog.at_level(logging.WARNING):
        warn_on_schema_mismatch(answer, {SCHEMA_KEY: SCHEMA}, "tag_page")

    (said,) = [record.getMessage() for record in caplog.records]
    assert said.startswith("Schema validation warning for 'tag_page': the answer did not parse")
    assert "_parse_error" not in said and "raw_response" not in said
    assert "agac retry" in said


def test_an_answer_that_parsed_is_still_checked_against_the_schema(caplog):
    with caplog.at_level(logging.WARNING):
        warn_on_schema_mismatch({"label": "a"}, {SCHEMA_KEY: SCHEMA}, "tag_page")

    (said,) = [record.getMessage() for record in caplog.records]
    assert "did not parse" not in said

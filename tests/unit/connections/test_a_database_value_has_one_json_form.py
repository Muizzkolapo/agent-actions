"""A record's identity is a hash of its content, so a value must read the same each time."""

import datetime
import decimal
import uuid

import pytest

from agent_actions.connections import json_safe
from agent_actions.errors import ConfigurationError
from agent_actions.utils.id_generation import IDGenerator


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (7, 7),
        (1.5, 1.5),
        ("text", "text"),
        (decimal.Decimal("10.50"), "10.50"),
        (decimal.Decimal("1E+2"), "100"),
        (datetime.date(2026, 11, 23), "2026-11-23"),
        (datetime.datetime(2026, 11, 23, 8, 30), "2026-11-23T08:30:00"),
        (datetime.time(8, 30), "08:30:00"),
        (datetime.timedelta(minutes=2), 120.0),
        (uuid.UUID(int=1), "00000000-0000-0000-0000-000000000001"),
        (b"\x00\xff", "AP8="),
        (
            {"when": datetime.date(2026, 1, 2), 3: [decimal.Decimal("1")]},
            {"when": "2026-01-02", "3": ["1"]},
        ),
        ((1, 2), [1, 2]),
    ],
)
def test_a_value_takes_its_json_form(value, expected):
    assert json_safe(value) == expected


def test_a_value_with_no_json_form_says_to_cast_it():
    with pytest.raises(ConfigurationError, match="type set has no JSON form; cast the column"):
        json_safe({1, 2})


def test_a_row_read_twice_has_one_identity():
    def row():
        return {"id": 1, "price": decimal.Decimal("9.90"), "at": datetime.datetime(2026, 1, 2)}

    first, second = ({name: json_safe(value) for name, value in row().items()} for _ in range(2))

    assert IDGenerator.derive_source_guid(first) == IDGenerator.derive_source_guid(second)

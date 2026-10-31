"""A non-string field name is rejected, not silently hashed into an ambiguous identity.

Stringifying keys to make them sortable is lossy: two keys that stringify to the same string
(a numeric spreadsheet header ``2024`` vs a text header ``"2024"``; a ragged csv row's ``None``
restkey vs a literal ``"None"`` column) would collapse into one, giving distinct rows the same
``source_guid`` — a silent dedup collision. Such a field name is also unusable downstream (it
becomes a content.source key referenced by name), so identity generation fails loud instead.
"""

import pytest

from agent_actions.errors import DataValidationError
from agent_actions.utils.id_generation import IDGenerator


def test_numeric_field_name_is_rejected():
    with pytest.raises(DataValidationError):
        IDGenerator.derive_source_guid({2024: "a", "name": "b"})


def test_none_field_name_is_rejected():
    # the None restkey a ragged csv row injects
    with pytest.raises(DataValidationError):
        IDGenerator.derive_source_guid({"a": "1", None: ["3"]})


def test_nested_non_string_key_is_rejected():
    with pytest.raises(DataValidationError):
        IDGenerator.derive_source_guid({"outer": {2024: "x"}})
